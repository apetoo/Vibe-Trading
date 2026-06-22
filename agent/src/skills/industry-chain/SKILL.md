---
name: industry-chain
description: >
  Industry chain knowledge graph for stock analysis. Before analyzing a stock,
  use get_industry_chain_context to find its position in the industry chain
  (赛道→技术方向→环节→个股), key metrics (国产化率/毛利率/市场规模), and
  competitors. The graph covers AI 算力产业链 (CPO/OCS/光芯片/PCB) as pilot.
  If a stock is not in the graph, use draft_industry_chain_update to propose
  adding it. The system auto-injects industry chain context when you mention
  a stock code that exists in the graph.
category: analysis
---

# Industry Chain Knowledge Graph

The industry chain knowledge graph provides structured, versioned industry
chain data for A-share stocks. It is organized as a 4-layer tree:

- **Track** (赛道): The broad industry theme, e.g. AI 算力产业链
- **Segment** (技术方向): Technology direction within the track, e.g. CPO, OCS
- **Link** (环节): Specific process/material step, e.g. 光模块, 光芯片
- **Stock** (个股): Listed company positioned at this link

## When to use

- **Before analyzing a stock**: Call `get_industry_chain_context` with the stock
  code to get its industry chain positioning, competitors, and key metrics.
  If the stock is not in the graph, you'll get a null result.
- **To update the graph**: Call `draft_industry_chain_update` with the fields
  to update. Each update needs at least one source citation. The change goes
  to a pending review queue — a human must approve it before it takes effect.
- **Auto-injection**: When you mention a stock code (e.g. 300308.SZ) that exists
  in the graph, the system automatically injects its industry chain context.

## Pilot scope

Currently covers **AI 算力产业链** (AI Compute Chain) with 4 segments:
- CPO (共封装光学)
- OCS (光交换)
- 光芯片 (Optical Chip)
- PCB (印制电路板)

## Data sources (constraint)

All data comes from: company annual reports, prospectuses (巨潮资讯网),
exchange announcements, and sell-side research reports.
No social media or blog sources are accepted.
