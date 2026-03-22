/**
 * Export Q&A to markdown format
 */
export function exportToMarkdown(userMessage, assistantMessage) {
  const timestamp = new Date().toISOString().split('T')[0];
  let md = `# LLM-TTCC-TEAM-PRO Response\n\n`;
  md += `**Date:** ${timestamp}\n\n`;
  md += `---\n\n`;

  // User question
  md += `## Question\n\n${userMessage}\n\n`;

  // Stage 1: Individual responses
  if (assistantMessage.stage1 && assistantMessage.stage1.length > 0) {
    md += `---\n\n## Stage 1: Individual Responses\n\n`;
    assistantMessage.stage1.forEach((resp) => {
      const modelName = resp.model.split('/')[1] || resp.model;
      md += `### ${modelName}\n\n${resp.response}\n\n`;
    });
  }

  // Stage 2: Rankings
  if (assistantMessage.stage2 && assistantMessage.stage2.length > 0) {
    md += `---\n\n## Stage 2: Peer Rankings\n\n`;

    const labelToModel = assistantMessage.metadata?.label_to_model || {};

    assistantMessage.stage2.forEach((rank) => {
      const modelName = rank.model.split('/')[1] || rank.model;
      md += `### Evaluation by ${modelName}\n\n`;

      // De-anonymize the ranking text
      let rankingText = rank.ranking;
      Object.entries(labelToModel).forEach(([label, model]) => {
        const shortName = model.split('/')[1] || model;
        rankingText = rankingText.replace(new RegExp(label, 'g'), `**${shortName}**`);
      });
      md += `${rankingText}\n\n`;
    });

    // Aggregate rankings
    const aggregateRankings = assistantMessage.metadata?.aggregate_rankings;
    if (aggregateRankings && aggregateRankings.length > 0) {
      md += `### Aggregate Rankings (Street Cred)\n\n`;
      md += `| Rank | Model | Avg Score | Votes |\n`;
      md += `|------|-------|-----------|-------|\n`;
      aggregateRankings.forEach((agg, index) => {
        const modelName = agg.model.split('/')[1] || agg.model;
        md += `| #${index + 1} | ${modelName} | ${agg.average_rank.toFixed(2)} | ${agg.rankings_count} |\n`;
      });
      md += `\n`;
    }
  }

  // Stage 3: Final answer
  if (assistantMessage.stage3) {
    md += `---\n\n## Stage 3: Final Council Answer\n\n`;
    const chairmanName = assistantMessage.stage3.model.split('/')[1] || assistantMessage.stage3.model;
    md += `**Chairman:** ${chairmanName}\n\n`;
    md += `${assistantMessage.stage3.response}\n`;
  }

  return md;
}

export function downloadMarkdown(content, filename) {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export function generateFilename(index) {
  return `llm-ttcc-team-pro-${new Date().toISOString().slice(0, 10)}-${index}.md`;
}
