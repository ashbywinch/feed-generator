# Industry, Manufacturing & Policy — Discovery Source List

Status: approved by reviewer loop (iteration 3). 8 subareas, 17 sources, 5 queries. Generated 2026-08-03.

## Subareas
### 1. High-Mix & Advanced Manufacturing (CNC, additive)

strong

- **MTDCNC** (`mtdcnc.com`) — trade press — high · crawl: https://mtdcnc.com/feed
  Daily CNC machining, 5-axis and machine-tool trade news; the reference feed for high-mix, low-volume shop-floor activity.
- **Additive3D Asia** (`additive3dasia.com`) — trade press — high · crawl: https://additive3dasia.com/feed
  Additive-manufacturing and hybrid-manufacturing news; covers the process-technology side of advanced manufacturing.

### 2. Reshoring & Industrial Base

strong

- **Reshoring Initiative** (`reshorenow.org`) — data/registry — high · crawl: https://reshorenow.org/blog/ and the Reshoring Initiative quarterly data reports
  Publishes the authoritative quarterly US reshoring & foreign direct investment job-count datasets the whole field cites.

### 3. Energy-Intensive Industry & Industrial Decarbonization

strong

- **Industry Decarbonization Newsletter** (`industrydecarbonization.com`) — newsletter — high · crawl: https://industrydecarbonization.com/rss.xml
  Hard-to-abate sector (steel, cement, chemicals, aluminium) electrification and decarbonisation policy feed.
- **Jan Rosenow (EnergyUtopia)** (`janrosenow.substack.com`) — independent blog — high · crawl: https://janrosenow.substack.com/feed
  First-principles analysis of industrial electrification and hard-to-electrify heat; strong on policy mechanics for energy-intensive industry.

### 4. SMRs & Heavy Industry / Nuclear New-Build

strong

- **SMR News & Headlines** (`smrheadlines.substack.com`) — newsletter — high · crawl: https://smrheadlines.substack.com/feed
  Dedicated small-modular-reactor newslog tracking SMR programme announcements, site approvals and vendor milestones.
- **SMR Insider** (`smrinsider.com`) — trade press — high · crawl: https://smrinsider.com/feed
  Sector-specific SMR news and innovation coverage across vendors, regulators and project finance.
- **World Nuclear News** (`world-nuclear-news.org`) — trade press — high · crawl: https://world-nuclear-news.org/rss
  Global nuclear industry news incl. SMR, Sizewell C and new-build financing; high-density industry feed.
- **Nuclear Electrical Engineer** (`nuclearelectricalengineer.com`) — independent blog — medium · crawl: https://nuclearelectricalengineer.com/feed
  Independent engineer's commentary on nuclear new-build economics, grid integration and SMR feasibility.

### 5. Defense Industrial Capacity

strong

- **Breaking Defense** (`breakingdefense.com`) — trade press — high · crawl: https://breakingdefense.com/feed/
  Defence programme and industrial-base news covering munitions production, supply chains and contract awards.
- **JINSA (Jewish Institute for National Security of America)** (`jinsa.org`) — think tank — high · crawl: https://jinsa.org/feed
  Regular munitions-and-industrial-base capacity assessments (e.g. 'Arsenal of Procrastination' reports).
- **Defense Acquisition / defenseacquisition.substack.com** (`defenseacquisition.substack.com`) — newsletter — medium · crawl: https://defenseacquisition.substack.com/feed
  Analysis of defense acquisition and the prime-contractor industrial base including mega-contract and funding trends.
- **CSIS Industrial Base program** (`csis.org`) — think tank — high · crawl: https://csis.org/rss.xml
  Flagship rapid cycles on US industrial base readiness, including 'Is the Industrial Base on a Wartime Footing?'.

### 6. Semiconductors & Critical Components

medium

- **The Semiconductor Newsletter** (`thesemiconductornewsletter.substack.com`) — newsletter — high · crawl: https://thesemiconductornewsletter.substack.com/feed
  Fab, tooling and chip-capacity weekly; captures the most strategically contested manufacturing subarea.

### 7. Supply Chains & Logistics

medium

- **Supply Chain Dive** (`supplychaindive.com`) — trade press — high · crawl: https://www.supplychaindive.com/feeds/news/
  Daily manufacturing supply-chain, reshoring, procurement and logistics news with a US industrial focus; a strong outside replacement for the previously subscribed MMH feed.

### 8. Industrial Policy, Trade & Incentives

strong

- **Information Technology and Innovation Foundation (ITIF)** (`itif.org`) — think tank — high · crawl: https://itif.org/feed
  Deep first-principles work on industrial policy, chip/CHIPS, tariffs, export controls and production incentives.
- **Center for Industrial Strategy (Charles Yang)** (`industrialstrategy.substack.com`) — independent blog — high · crawl: https://industrialstrategy.substack.com/feed
  First-principles analysis of industrial policy design, incentives and production base-building; keeps this subarea strong after retiring the industryweek.com duplicate listing.

## Registries
- **FRED Industrial Production Index** (`fred.stlouisfed.org`) — Federal Reserve monthly industrial production and capacity utilisation series (INDPRO) — the core empirical registry of manufacturing output.
- **US Census Bureau Manufacturing (M3)** (`census.gov`) — Monthly manufacturers' shipments, inventories and orders (M3) — authoritative US factory-activity series.
- **BEA Manufacturing Value Added** (`bea.gov`) — GDP/industry value-added series for durable and nondurable manufacturing; has an RSS feed for release announcements.
- **USAspending / Federal Procurement** (`usaspending.gov`) — Prime-award and defense procurement database — grounding data for defense-industrial-capacity and reshoring contract analysis.
- **Reshoring Initiative Job Count Database** (`reshorenow.org`) — Quarterly reshoring & FDI job-announcement counts; the field's reference dataset for reshoring trend analysis.

## Queries
1. reshoring US manufacturing job announcements data
2. industrial base capacity munitions and defense production analysis
3. small modular reactor SMR heavy industry nuclear new build deployment
4. energy intensive industry decarbonization steel cement electrification policy
5. high mix low volume CNC additive manufacturing reshoring supply chain

## News vs analysis
News-forward sources: MTDCNC, Additive3D Asia, IndustryWeek, World Nuclear News, Breaking Defense, SMR Insider, MMH, SMR News & Headlines, Industry Decarbonization Newsletter. Analysis-forward sources: CSIS, ITIF, JINSA, IISS, Jan Rosenow, Nuclear Electrical Engineer, The Semiconductor Newsletter, Defense Acquisition newsletter.

## Notes
Excluded the user's blacklisted domains (hydraraptor.blogspot.com, toolordie.com). No sources from the 'out' scope (consumer products, software, services). Source-type mix spans trade press, newsletters, independent blogs, think tanks and data registries (≥4 distinct types). Every domain was verified with check_url for DNS+feed before inclusion; sources without a discoverable feed (reshorenow.org, fred, census, usaspending, bea) are included as data/registry entries with explicit crawl_root/API endpoints per rule 11 rather than HTML crawling. Defense overlaps Geopolitics by design (the topic notes this overlap); sources stay on industrial capacity, not consumer/military-ops content. SMR subarea is intentionally deep (4 sources) as it is a named 'in' item with high event density.

## Review record
- [minor] Subarea completeness: Two implied-but-important subareas carry only a single source each: Semiconductors & Critical Components and Supply Chains & Logistics (both 'medium', 1 source apiece). Semiconductors is described as the most strategically contested manufacturing subarea and would benefit from a second outside source (e.g., an additional chip-policy/industry feed) to match the 2+ bar for major subareas.
- [minor] Engine-actionable / metadata hygiene: The 'news_vs_analysis' field references sources that do not exist anywhere in the subareas/sources lists: 'IndustryWeek', 'MMH', and 'IISS'. The 'why' lines also reference 'retiring the industryweek.com duplicate listing' and 'previously subscribed MMH feed'. These dangling references could mislead the pipeline into expecting sources that are not present.
- [minor] Engine-actionable / crawl_root formatting: Several data/registry entries (reshorenow.org, FRED, Census M3) mix a URL with prose description inside crawl_root (e.g., 'https://reshorenow.org/blog/ and the Reshoring Initiative quarterly data reports', 'FRED JSON/CSV API ... via fredgraph (https://fred.stlouisfed.org/graph/fredgraph.csv?id=INDPRO)'). This is less engine-actionable than a single pinned endpoint.
