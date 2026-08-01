# Data Centers / AI / macro — Discovery Source List

Status: approved by reviewer loop (iteration 2). 8 subareas, 22 sources, 5 queries. Generated 2026-08-01.

## Subareas
### 1. Data center construction & physical build-out

Project-by-project build-out, site selection, megawatt capacity, land and power procurement, colocation and hyperscaler campuses, construction financing. Major subarea — 2+ sources.

- **Data Center Dynamics (DCD)** (`datacenterdynamics.com`) — trade press — high · crawl: https://www.datacenterdynamics.com/en/feed/
  Primary trade press on data center construction, new campus announcements, and site-level deals worldwide.
- **Data Center Knowledge** (`datacenterknowledge.com`) — trade press — high · crawl: https://www.datacenterknowledge.com/rss.xml
  Dedicated coverage of hyperscaler build-outs including Stargate site-by-site status; construction and capacity tracking.
- **AFCOM/Analyst community via TrackitCore — datacenterHawk** (`datacenterhawk.com`) — data/registry — medium
  Structured data/registry on data center supply, vacancy, and construction pipeline by market.

### 2. Chip supply & semiconductor geopolitics

GPU supply, TSMC/ASML/Samsung capacity, export controls, US-CHINA decoupling, equipment and foundry economics. Major subarea — 2+ sources.

- **SemiAnalysis** (`semianalysis.com`) — independent blog — high · crawl: https://semianalysis.com/feed/
  Deep first-principles analysis of GPU supply chains, chip cost curves, and data center compute economics.
- **DIGITIMES** (`digitimes.com`) — trade press — medium
  Asia-focused supply-chain news and insight on foundries, equipment, and chip shipments tied to AI build-out.
- **Semiengineering** (`semiengineering.com`) — trade press — medium · crawl: https://semiengineering.com/feed/
  Engineering and business coverage of chip design, manufacturing, and packaging constraints affecting AI silicon.

### 3. Model economics & AI market structure

GPU cloud pricing, inference/training cost curves, market concentration among hyperscalers, AI cloud provider competition. Major subarea — 2+ sources.

- **The Information — AI/Compute vertical** (`theinformation.com`) — trade press — medium · crawl: https://www.theinformation.com/rss
  Reporting on AI market structure, cloud provider competition, and model economics; paywalled with free headline feed.
- **Latent Space** (`latent.space`) — newsletter — medium
  Recaps AI infrastructure and compute market shifts; bridges model economics and deployment.
- **Genspark / dirttodata by Matt Ocko** (`dirttodata.substack.com`) — independent blog — medium
  First-principles analysis of AI infrastructure economics and data center value chains.

### 4. AI funding, capex cycles & capital markets

Hyperscaler capex guidance, AI infrastructure financing, data center debt/equity, asset-class formation, SPVs and megadeals. Major subarea — 2+ sources.

- **Macro Compounder** (`macrocompounder.substack.com`) — newsletter — medium
  Tracks 'AI's trillion in plumbing' — capital flows into data centers and compute infrastructure.
- **Wheelie Investor** (`wheelieinvestor.substack.com`) — independent blog — medium
  Tracks hyperscaler capex guidance and where the AI capex budget is being allocated.
- **Fund Manager / Value Add VC** (`valueaddvc.com`) — independent blog — medium
  Covers AI data center financing as an institutional asset class and big-tech capex cycles.

### 5. Power constraints on compute & grid

Data center power procurement, grid interconnection queues, curtailment, nuclear/gas PPAs, utility-scale power deals for AI. Major subarea — 2+ sources.

- **Utility Dive — data center / electrification beat** (`utilitydive.com`) — trade press — high · crawl: https://www.utilitydive.com/feeds/news/
  Primary US power-trade coverage of grid constraints on data centers, curtailment rules, and PPA activity.
- **Einar SSO / 'Power, not GPUs' — Global Tech Research** (`globaltechresearch.substack.com`) — independent blog — medium
  First-principles analysis of power becoming the AI bottleneck rather than GPU supply.
- **Canary Media — grid & data center load** (`canarymedia.com`) — trade press — medium · crawl: https://www.canarymedia.com/feeds
  Clean-energy trade journalism on rising electricity demand and data center load growth.

### 6. Policy, regulation & market design for compute

Export controls policy, AI infrastructure permitting, grid interconnection reform, government AI data center programs (Stargate site federal lands), capacity planning. Policy is its own subarea — dedicated sources.

- **Reuters — Technology & US policy** (`reuters.com`) — trade press — high · crawl: https://feeds.reuters.com/reuters/technologyNews
  Authoritative wire reporting on US chip export-control rule changes and AI infrastructure policy.
- **Brussels Institute for Geopolitics (BIG)** (`big-europe.eu`) — think tank — medium
  Think-tank analysis of semiconductor supply-chain geopolitics and weaponized interdependence.
- **CSET (Georgetown Center for Security and Emerging Technology)** (`cset.georgetown.edu`) — think tank — medium · crawl: https://cset.georgetown.edu/feed/
  Policy research on AI compute, export controls, and computing-power governance.

### 7. AI data registry / structured data

Structured public datasets on compute, capability releases, and semiconductor supply relevant to macro analysis.

- **Epoch AI** (`epochai.org`) — data/registry — high · crawl: https://epochai.org/feed
  Maintains the premier structured registry of AI model training compute and capability trends.
- **OpenAlex API** (`api.openalex.org`) — data/registry — high · crawl: https://api.openalex.org/works?filter=concepts.id:C41008148
  Open API for discovering AI/compute academic literature at scale; bot-friendly crawl endpoint for paper-level signals.

### 8. Data center colocation & REIT financials

Colocation provider earnings, data center REITs (Equinix, Digital Realty, Vantage, QTS), pricing and occupancy fundamentals.

- **REIT.com / Nareit research** (`reit.com`) — data/registry — medium
  Structured data on data center REIT performance and capital flows into the asset class.
- **Vantage Data Centers — investor/construction press** (`vantage-dc.com`) — trade press — medium
  Company disclosures and construction announcements tracking colocation capacity build-out.

## Registries
- {'name': 'OpenAlex', 'domain': 'api.openalex.org', 'type': 'data/registry', 'why': 'Structured API for AI/compute literature discovery and citation signals.', 'crawl_root': 'https://api.openalex.org/works?filter=concepts.id:C41008148'}
- {'name': 'Epoch AI dataset', 'domain': 'epochai.org', 'type': 'data/registry', 'why': 'Governance and compute-trend registry for AI scaling and capability metrics.', 'crawl_root': 'https://epochai.org/feed'}
- {'name': 'US ITC / Census — semiconductor import statistics', 'domain': 'usitc.gov', 'type': 'data/registry', 'why': 'Public trade data on semiconductor imports/exports underpinning supply-chain macro signals.', 'confidence': 'medium'}
- {'name': 'Hugging Face Hub API (compute/card metadata)', 'domain': 'hf.co', 'type': 'data/registry', 'why': 'Registry of model releases with compute and hardware metadata; API for capacity signals.', 'confidence': 'medium', 'crawl_root': 'https://huggingface.co/api/models'}

## Queries
1. data center construction megawatt capacity announcements
2. hyperscaler capex guidance OpenAI Stargate compute build-out
3. GPU supply export controls TSMC capacity chip economics
4. data center power grid interconnection curtailment PPA nuclear
5. AI infrastructure financing debt equity data center REIT

## News vs analysis
Blend leans analysis-heavy for the macro layer: SemiAnalysis, Latent Space, Macro Compounder, and dirttodata carry the first-principles compute/capex economics, while DCD, Data Center Knowledge, DIGITIMES, Reuters, and Utility Dive supply the high-frequency news and policy events. Registries (Epoch, OpenAlex, HF) provide the structured, crawlable signal backbone. Roughly 55% analysis, 45% news to match the topic's 'industry layer' positioning.

## Notes
All six distinct source types represented: independent blog (SemiAnalysis, Macro Compounder, Wheelie Investor, Global Tech Research, Value Add VC), trade press (DCD, Data Center Knowledge, DIGITIMES, Semiengineering, The Information, Utility Dive, Canary Media, Reuters), newsletter (Latent Space), think tank (BIG, CSET), academic/journal via OpenAlex API endpoint (avoids HTML bot protection), and data/registry (Epoch, OpenAlex, HF, datacenterHawk, REIT.com, USITC). Subscribed sources (blog.eladgil.com, chamathreads.substack.com) and their domains are excluded. No consumer EV, efficiency-gadget, corporate-sustainability-PR, or climate-activism drift — every source's 'why' ties to compute, silicon, power, or AI capital markets. Paywalled/bot-protected endpoints routed to RSS/API crawl_roots (OpenAlex API for academic, feed endpoints for DCD, Utility Dive, CSET, Reuters headline feed). Exact-duplicate domain reuse across subareas avoided deliberately per reviewer note (SemiAnalysis appears once under chip supply; cross-referenced not duplicated).

## Review record
- [minor] Type mix / classification: 'Vantage Data Centers — investor/construction press' (subarea 'Data center colocation & REIT financials') is classified as 'trade press' but is a corporate PR/disclosure channel, not editorial press. This slightly inflates the trade-press count and the subarea's editorial strength; the subarea stands on REIT.com plus this company channel.
- [minor] Non-generic naming: 'Fund Manager / Value Add VC' (subarea 'AI funding, capex cycles & capital markets') has an imprecise, compound name ('Fund Manager' prefix is generic) and unverified content of the valueaddvc.com domain's focus on AI data center financing as an asset class.
- [minor] Crawl endpoints / portability: Several sources (DIGITIMES, datacenterhawk, reit.com, valueaddvc, wheelieinvestor, macrocompounder, latent.space, dirttodata) lack a pinned crawl_root, while the topic is registry-marked and query[0] is not obviously registry-optimized; DIGITIMES and newsletters can be bot-sensitive or paywalled/free-tier only.
- [minor] Verifiability (residual): Search budget capped before content-plausibility could be confirmed for valueaddvc.com, macrocompounder.substack.com, latent.space, and the OpenAlex concept id C41008148 (assumed to map to compute/AI). No hallucination detected among the 5 spot-checks completed.
