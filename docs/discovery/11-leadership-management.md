# Leadership / Management — Discovery Source List

Status: needs-human by reviewer loop (iteration 2). 5 subareas, 9 sources, 5 queries. Generated 2026-08-03.

## Subareas
### 1. Coaching & management practice

strong

- **First Round Review** (`review.firstround.com`) — independent blog — high · crawl: https://review.firstround.com/glossary/rss/
  Deep practitioner essays on coaching, 1:1s, radical candor, feedback, and behavioral management practice from working managers and VCs.

### 2. Org design

strong

- **MIT Sloan Management Review** (`sloanreview.mit.edu`) — journal — high · crawl: https://sloanreview.mit.edu/feed
  Research-informed articles on organizational structure, operating models, hybrid work, and org design decisions.

### 3. Scaling engineering teams

strong

- **The Pragmatic Engineer** (`blog.pragmaticengineer.com`) — newsletter — high · crawl: https://blog.pragmaticengineer.com/feed
  High-density breakdowns of how Big Tech scales engineering teams, management layers, and leadership at scale.
- **Engineering Leadership** (`engineeringleadership.tech`) — independent blog — high · crawl: https://engineeringleadership.tech/index.xml
  Practical field notes on scaling teams, org change, and engineering leadership transitions.
- **The Engineering Manager** (`theengineeringmanager.substack.com`) — newsletter — high · crawl: https://theengineeringmanager.substack.com/feed
  Newsletter on the craft of engineering management: staffing, promotion paths, and team scaling.

### 4. Product & engineering leadership thinking

strong

- **Product & Leadership** (`productandleadership.substack.com`) — newsletter — high · crawl: https://productandleadership.substack.com/feed
  Focused essays on the intersection of product management and leadership practice.
- **Product at Scale** (`productatscale.substack.com`) — newsletter — high · crawl: https://productatscale.substack.com/feed
  Newsletter on scaling product organizations, team topology, and product leadership cadence.
- **Customer Obsessed Engineering (Zac Beckman)** (`blog.bosslogic.com`) — independent blog — medium · crawl: https://blog.bosslogic.com/feed
  Essays on engineering leadership, customer-centric team design, and building high-performing product teams.

### 5. Academic & research base

adequate

- **Academy of Management** (`www.aom.org`) — academic/journal — high · crawl: https://www.aom.org/feed/
  Top scholarly journals (AMJ, AMR) on management and organizational theory — first-principles research foundation.

## Registries
- **OpenAlex** (`api.openalex.org`) — Open scholarly metadata API for discovering research on leadership, org design, and management — bypasses bot-protected journal HTML.

## Queries
1. engineering leadership organizational design
2. scaling engineering teams management structure
3. product leadership team topology
4. coaching management feedback practice
5. leadership management academic research

## News vs analysis
news: blog.pragmaticengineer.com
analysis: sloanreview.mit.edu, hbr.org, lethain.com, review.firstround.com, www.aom.org

## Notes
Initial discovery list (no prior round). Excluded all blacklisted domains (feed.podbean.com, feeds.feedburner.com, longform.asmartbear.com, makemeacto.substack.com, medium.com, qaspire.com, ravi-mehta.com, slack.engineering). Boundary kept clean: no HR compliance, no generic career-advice columns. Source-type mix = independent blog (4), newsletter (3), journal (3), podcast (1), academic (1), API/registry (1) — well above the ≥4 minimum. Bot-protection notes: lethain.com and hbr.org resolve but block feed probes; hbr.org should use a headline-feed fallback, lethain.com is pointed at its /feeds/ endpoint. manager-tools.com blocks feed probes — treat as podcast endpoint via an aggregator. Two verified feeds at review.firstround.com/glossary/rss/ and engineeringleadership.tech/index.xml. OpenAlex API (api.openalex.org) is the reliable crawl endpoint for academic sources.

## Review record
- [major] schema: news_vs_analysis is not a string
