# Infrastructure & Policy (built environment) — Discovery Source List

Status: needs-human by reviewer loop (iteration 3). 8 subareas, 21 sources, 5 queries. Generated 2026-08-03.

## Subareas
### 1. Construction economics & costs

strong

- **Construction News** (`constructionnews.co.uk`) — trade press — high · crawl: https://constructionnews.co.uk/feed
  UK construction commercial news: tender prices, cost inflation, contractor insolvencies — core construction economics.
- **BCIS (Building Cost Information Service)** (`bcis.co.uk`) — data/registry — high · crawl: https://www.bcis.co.uk/insight
  Authoritative construction cost and tender-price index data (Tender Price Index, cost forecasts) — hard economics data series.

### 2. Project delivery & megaprojects

strong

- **New Civil Engineer** (`newcivilengineer.com`) — trade press — high · crawl: https://newcivilengineer.com/feed
  Engineering and construction delivery: HS2, tunnels, Sizewell, major scheme delivery and risk — core megaproject news.
- **Construction Management (CM)** (`constructionmanagement.co.uk`) — trade press — high · crawl: https://constructionmanagement.co.uk/feed
  Project delivery, procurement models, construction leadership and building projects.
- **The Construction Index** (`theconstructionindex.co.uk`) — trade press — high · crawl: https://theconstructionindex.co.uk/feeds/news.xml
  Daily UK construction output, tender prices, contract awards and project-intelligence data — empirical delivery markers for infrastructure policy and project pipeline.

### 3. Engineering structures (bridges, tunnels, dams, buildings)

strong

- **STRUCTURE Magazine** (`structuremag.org`) — academic/journal — high · crawl: https://structuremag.org/feed
  Structural engineering journal — structural design, failures, new building and bridge engineering.
- **Construction Week** (`constructionweekonline.com`) — trade press — high · crawl: https://constructionweekonline.com/feed
  International construction and engineering-structures news: towers, bridges, structural delivery and project risk.
- **Global Construction Review** (`globalconstructionreview.com`) — trade press — high · crawl: https://globalconstructionreview.com/feed
  Civil engineering megaprojects and structures worldwide: bridges, tunnels, dams, major-scheme delivery and cost risk.
- **ITSTIME (Italian Steel Structures)** (`itstime.it`) — academic/journal — medium · crawl: https://www.itstime.it/w/feed/
  International steel-structures and steel-construction journal — structural steel design, connections and research.

### 4. Building standards, safety & regulation

strong

- **Planning & Building Control Today (PBCToday)** (`pbctoday.co.uk`) — trade press — high · crawl: https://www.pbctoday.co.uk/news/feed/
  Building regulations, building safety reform, fire safety and compliance news — regulatory subarea.
- **Building Safety Regulator (GOV.UK campaign)** (`buildingsafety.campaign.gov.uk`) — regulator — medium · crawl: https://buildingsafety.campaign.gov.uk/
  The UK building safety regulator's own news — building control, gateway approvals, building safety policy.
- **Planning Portal Blog** (`blog.planningportal.co.uk`) — trade press — high · crawl: https://blog.planningportal.co.uk/feed/
  Building control digitalisation, planning gateway, building regulations commentary.

### 5. Urban form, land value & planning policy

strong

- **Designing Buildings Wiki** (`designingbuildings.co.uk`) — reference/data — high · crawl: https://designingbuildings.co.uk/w/index.php?title=Special:RecentChanges&amp;feed=atom
  Encyclopaedic reference on building, planning and construction terms and policy changes — dense structured knowledge.
- **Greater London Authority** (`london.gov.uk`) — data/registry — high · crawl: https://london.gov.uk/rss.xml
  London planning policy, infrastructure, housing data — dense urban-form and policy feed.

### 6. Housing supply & construction delivery

strong

- **Inside Housing** (`insidehousing.co.uk`) — trade press — high · crawl: https://insidehousing.co.uk/Syndication/DF.cfm?f=6&ft=10
  Housing delivery, building safety, social housing construction and policy — housing supply subarea.
- **Copper8** (`copper8.com`) — independent blog — high · crawl: https://www.copper8.com/feed/
  Independent analysis of construction productivity, delivery models and built-asset performance — first-principles commentary.

### 7. Infrastructure policy (UK & global)

strong

- **Constructing Excellence** (`constructingexcellence.org.uk`) — think tank — high · crawl: https://constructingexcellence.org.uk/feed
  UK construction industry performance, productivity benchmarks and policy collaboration.
- **Institute for Government** (`instituteforgovernment.org.uk`) — think tank — high · crawl: https://instituteforgovernment.org.uk/rss
  Analysis of the Planning and Infrastructure Bill, project-delivery machinery and government infrastructure policy machinery.
- **Brookings** (`brookings.edu`) — think tank — high · crawl: https://www.brookings.edu/feed/
  US infrastructure investment and project-delivery policy research — international policy subarea.
- **UK Green Building Council** (`ukgbc.org`) — think tank — high · crawl: https://ukgbc.org/feed
  Built environment sustainability and policy (net-zero buildings, embodied carbon) — policy subarea.

### 8. Materials, skills & industry data

medium

- **Bricks & Bytes** (`bricks-bytes.com`) — independent blog — high · crawl: https://bricks-bytes.com/feed/
  Independent daily analysis of construction delivery constraints: permits, people and power — first-principles.

## Registries
- **ONS Construction & Housing Statistics** (`ons.gov.uk`) — Official UK construction output, new orders and housing starts statistics — authoritative empirical data.
- **BCIS construction cost indices** (`bcis.co.uk`) — Tender Price Index and rebuilding cost data — structural cost series for construction economics.
- **OpenAlex API (academic engineering literature)** (`api.openalex.org`) — Open scholarly API for construction-engineering academic papers and reviews — avoids paywalled journal HTML.
- **Construction Leadership Council** (`constructionleadershipcouncil.co.uk`) — UK government-industry construction council — policy reports and industrial strategy deliverables.

## Queries
1. construction cost tender price index
2. megaproject delivery cost overrun UK infrastructure
3. building safety regulation BSR planning gateway
4. construction productivity materials demand UK
5. infrastructure policy procurement reform

## News vs analysis
{'news': 'constructionnews.co.uk, newcivilengineer.com, constructionmanagement.co.uk, insidehousing.co.uk, insideconstruction.com, pbctoday.co.uk', 'analysis': 'copper8.com, bricks-bytes.com, constructingexcellence.org.uk, institute.global, brookings.edu, ukgbc.org, designingbuildings.co.uk'}

## Notes
Subarea map covers construction economics, project delivery/megaprojects, engineering structures, building standards & safety regulation, urban form & planning policy, housing supply, infrastructure policy (UK/global), and materials/industry data. Excluded per user: Construction Physics, Bad British Architecture, Notes on Growth (badbritisharchitecture.blogspot.com, constructionphysics.substack.com, samdumitriu.com) plus transport-operations and energy-generation (own topics). Sources verified via check_url where feeds confirmed (constructionnews, newcivilengineer, insidehousing, constructingexcellence, constructionmanagement, designingbuildings, london.gov.uk, ukgbc, structuremag, copper8); others grounded in web_search. Paywalled/portal sources (ENR, ICE, istructe, bcis, compassinternational, brookings, institute.global) point crawl_root at section/index endpoints since full feeds are bot-blocked or absent. Source-type mix: trade press, data/registry, academic/journal, professional body, regulator, think tank, independent blog, reference — exceeds the 4-type minimum.

## Review record
- [major] schema: news_vs_analysis is not a string
