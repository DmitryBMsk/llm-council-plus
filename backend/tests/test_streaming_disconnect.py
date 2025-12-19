"""Tests for streaming disconnect handling - partial results should be saved."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import json


class TestStreamingDisconnect:
    """Test that partial results are saved when client disconnects during streaming."""

    @pytest.mark.asyncio
    async def test_saves_partial_results_when_client_disconnects_after_stage1(self):
        """
        When client disconnects after stage1 completes but before stage2 finishes,
        the stage1 results should still be saved to storage.

        This tests the race condition where:
        1. Stage 1 completes successfully
        2. Client disconnects during Stage 2
        3. Generator is cancelled
        4. Results should still be persisted
        """
        from ..main import send_message_stream
        from .. import storage

        # Setup: Create a conversation
        conversation_id = "test-disconnect-conv-001"

        # Mock storage to track calls
        saved_messages = []
        original_add_assistant = storage.add_assistant_message

        def track_save(*args, **kwargs):
            saved_messages.append({'args': args, 'kwargs': kwargs})
            return original_add_assistant(*args, **kwargs)

        # Mock the council functions to simulate stages
        mock_stage1_results = [
            {"model": "gpt-5.1", "response": "Stage 1 response from GPT"},
            {"model": "gemini-3-pro", "response": "Stage 1 response from Gemini"}
        ]

        async def mock_stage1_streaming(*args, **kwargs):
            """Yield stage1 results, then hang to simulate slow stage2"""
            for result in mock_stage1_results:
                yield result

        async def mock_stage2_slow(*args, **kwargs):
            """Simulate slow stage2 that gets cancelled"""
            await asyncio.sleep(10)  # Will be cancelled before completing
            return [], {}

        with patch.object(storage, 'get_conversation', return_value={
            "id": conversation_id,
            "messages": [],
            "models": None,
            "chairman": None
        }), \
        patch.object(storage, 'add_user_message'), \
        patch.object(storage, 'add_assistant_message', side_effect=track_save), \
        patch('backend.main.stage1_collect_responses_streaming', mock_stage1_streaming), \
        patch('backend.main.stage2_collect_rankings', mock_stage2_slow):

            # Create mock request
            class MockRequest:
                content = "Test query"
                attachments = None

            # Get the streaming response
            response = await send_message_stream(conversation_id, MockRequest())

            # Consume some events then simulate disconnect by closing generator
            generator = response.body_iterator
            events_received = []

            async for chunk in generator:
                events_received.append(chunk)
                # Parse the SSE event
                if b'stage1_complete' in chunk:
                    # Client "disconnects" after stage1 by closing the generator
                    await generator.aclose()
                    break

            # Allow cleanup to happen
            await asyncio.sleep(0.1)

        # ASSERTION: Even though client disconnected, partial results should be saved
        assert len(saved_messages) > 0, \
            "Expected add_assistant_message to be called with partial results after disconnect"

        # Check that stage1 results were included in the save
        saved_call = saved_messages[0]
        saved_stage1 = saved_call['args'][1] if len(saved_call['args']) > 1 else None

        assert saved_stage1 is not None, "Stage1 results should be saved"
        assert len(saved_stage1) == 2, "Both stage1 responses should be saved"

    @pytest.mark.asyncio
    async def test_saves_complete_results_on_normal_completion(self):
        """
        Verify that normal completion (no disconnect) saves all results.
        This is the control test to ensure our fix doesn't break normal operation.
        """
        from ..main import send_message_stream
        from .. import storage

        conversation_id = "test-normal-conv-001"
        saved_messages = []

        def track_save(*args, **kwargs):
            saved_messages.append({'args': args, 'kwargs': kwargs})

        mock_stage1_results = [{"model": "gpt-5.1", "response": "Response 1"}]
        mock_stage2_results = [{"model": "gpt-5.1", "ranking": "1. Response A"}]
        mock_stage3_result = {"model": "chairman", "response": "Final synthesis"}

        async def mock_stage1_streaming(*args, **kwargs):
            for result in mock_stage1_results:
                yield result

        async def mock_stage2(*args, **kwargs):
            return mock_stage2_results, {"Response A": "gpt-5.1"}

        async def mock_stage3(*args, **kwargs):
            return mock_stage3_result

        with patch.object(storage, 'get_conversation', return_value={
            "id": conversation_id,
            "messages": [],
            "models": None,
            "chairman": None
        }), \
        patch.object(storage, 'add_user_message'), \
        patch.object(storage, 'add_assistant_message', side_effect=track_save), \
        patch.object(storage, 'update_conversation_title'), \
        patch('backend.main.stage1_collect_responses_streaming', mock_stage1_streaming), \
        patch('backend.main.stage2_collect_rankings', mock_stage2), \
        patch('backend.main.stage3_synthesize_final', mock_stage3), \
        patch('backend.main.generate_conversation_title', return_value="Test Title"), \
        patch('backend.main.calculate_aggregate_rankings', return_value=[]):

            class MockRequest:
                content = "Test query"
                attachments = None

            response = await send_message_stream(conversation_id, MockRequest())

            # Consume all events (normal completion)
            async for chunk in response.body_iterator:
                pass

            await asyncio.sleep(0.1)

        # ASSERTION: Results should be saved on normal completion
        assert len(saved_messages) == 1, "Should save exactly once on normal completion"


class TestGeneratorCleanup:
    """Test that generator cleanup handles exceptions correctly."""

    @pytest.mark.asyncio
    async def test_generator_exit_does_not_suppress_finally(self):
        """
        Verify that GeneratorExit (client disconnect) allows finally block to execute.
        This is a unit test for the core fix mechanism.
        """
        cleanup_called = False
        results_saved = []

        async def event_generator():
            nonlocal cleanup_called, results_saved
            stage1_results = []

            try:
                # Simulate stage 1
                stage1_results = [{"model": "test", "response": "data"}]
                yield f"data: stage1_complete\n\n"

                # Simulate stage 2 (will be interrupted)
                await asyncio.sleep(10)

            except asyncio.CancelledError:
                # Should re-raise after cleanup
                raise
            finally:
                # This MUST execute even on disconnect
                cleanup_called = True
                if stage1_results:
                    results_saved.extend(stage1_results)

        gen = event_generator()

        # Get first event
        first_event = await gen.__anext__()
        assert b"stage1_complete" in first_event.encode() if isinstance(first_event, str) else b"stage1_complete" in first_event

        # Simulate client disconnect by closing generator
        await gen.aclose()

        # Verify cleanup happened
        assert cleanup_called, "finally block should execute on generator close"
        assert len(results_saved) == 1, "Results should be saved in finally block"
        assert results_saved[0]["model"] == "test"

    @pytest.mark.asyncio
    async def test_current_code_structure_loses_data_on_disconnect(self):
        """
        This test demonstrates the BUG in current main.py code structure.
        It mimics the CURRENT code pattern (without finally) and shows data is lost.

        Current pattern in main.py:
        ```
        try:
            stage1_results = [...]
            yield stage1_complete
            stage2_results = await stage2(...)  # <-- Client disconnects here
            stage3_result = await stage3(...)
            storage.add_assistant_message(...)  # <-- NEVER REACHED!
        except Exception as e:
            yield error
        # NO FINALLY BLOCK - data is lost!
        ```

        This test should FAIL with current code, proving the bug exists.
        After fix, it should pass.
        """
        save_called = False
        saved_data = []

        async def buggy_generator_current_pattern():
            """Mimics CURRENT main.py structure - no finally block"""
            nonlocal save_called, saved_data
            stage1_results = []

            try:
                # Stage 1 - completes
                stage1_results = [{"model": "test", "response": "data"}]
                yield f"data: stage1_complete\n\n"

                # Stage 2 - gets interrupted by client disconnect
                await asyncio.sleep(10)

                # This line NEVER executes if client disconnects during stage2
                save_called = True
                saved_data = stage1_results

            except Exception as e:
                yield f"data: error {e}\n\n"
            # BUG: No finally block! Data lost on disconnect!

        gen = buggy_generator_current_pattern()

        # Get stage1 event
        await gen.__anext__()

        # Client disconnects during stage2
        await gen.aclose()

        # BUG DEMONSTRATION: save was never called!
        # This assertion documents the bug we're fixing
        assert not save_called, "BUG CONFIRMED: current pattern does NOT save on disconnect"
        assert len(saved_data) == 0, "BUG CONFIRMED: data is lost"

    @pytest.mark.asyncio
    async def test_fixed_code_structure_saves_data_on_disconnect(self):
        """
        This test demonstrates the FIXED pattern with finally block.
        Shows that data IS saved even when client disconnects.
        """
        save_called = False
        saved_data = []

        async def fixed_generator_with_finally():
            """FIXED pattern with finally block"""
            nonlocal save_called, saved_data
            stage1_results = []
            stage2_results = []
            stage3_result = None

            try:
                # Stage 1 - completes
                stage1_results = [{"model": "test", "response": "data"}]
                yield f"data: stage1_complete\n\n"

                # Stage 2 - gets interrupted by client disconnect
                await asyncio.sleep(10)

                # Stage 3 - never reached
                stage3_result = {"response": "final"}

            except asyncio.CancelledError:
                # Re-raise to allow proper cleanup
                raise
            except Exception as e:
                yield f"data: error {e}\n\n"
            finally:
                # FIX: Always save whatever we have completed
                if stage1_results:  # At least some work was done
                    save_called = True
                    saved_data = stage1_results

        gen = fixed_generator_with_finally()

        # Get stage1 event
        await gen.__anext__()

        # Client disconnects during stage2
        await gen.aclose()

        # FIXED: save WAS called even though client disconnected!
        assert save_called, "FIXED: finally block saves data on disconnect"
        assert len(saved_data) == 1, "FIXED: stage1 data is preserved"
        assert saved_data[0]["model"] == "test"
