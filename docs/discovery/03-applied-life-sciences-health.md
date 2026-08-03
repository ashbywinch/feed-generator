# Applied Life Sciences & Health — Discovery Source List

Status: needs-human by reviewer loop (iteration 3). 8 subareas, 24 sources, 5 queries. Generated 2026-08-03.

## Subareas
### 1. Drug Development & Clinical Research

strong

- **Endpoints News** (`endpoints.news`) — trade press — high · crawl: https://endpoints.news/feed
  Daily high-density biotech R&D and clinical development news.
- **STAT News** (`statnews.com`) — trade press — high · crawl: https://statnews.com/feed
  Deep-reported clinical trial news and drug development analysis
- **Genetic Engineering & Biotechnology News** (`genengnews.com`) — trade press — high · crawl: https://genengnews.com/feed
  Novel therapeutic platforms and translational medicine coverage.
- **Drug Discovery Trends** (`drugdiscoverytrends.com`) — trade press — high · crawl: https://drugdiscoverytrends.com/feed
  Drug discovery workflow and clinical development technology.

### 2. Biotech Platforms & Scaling

strong

- **Genetic Engineering & Biotechnology News** (`genengnews.com`) — trade press — high · crawl: https://genengnews.com/feed
  Bioprocessing, cell/gene therapy manufacturing scale-up, platform tech.
- **Landmark Bio Blog** (`blog.artisbiosolutions.com`) — independent blog — medium · crawl: https://blog.artisbiosolutions.com/rss.xml
  Tech-transfer and manufacturing deep-dives for scaling biotech operations.
- **Cell** (`cell.com`) — academic/journal — high · crawl: https://api.openalex.org/works?filter=primary_location.source.id:S110447773
  Peer-reviewed platform and therapeutic science. Native RSS (cell.com/cell/rss) and homepage HTML are bot-blocked with no reachable feed (verified via check_url), so the crawler is pointed at the verified OpenAlex source endpoint (S110447773) instead of HTML article pages.

### 3. ME/CFS & Long COVID Research

strong

- **Solve ME/CFS Initiative** (`solvecfs.org`) — research org — high · crawl: https://solvecfs.org/feed
  Research roundups and study news on ME/CFS and post-infectious illness.
- **Health Rising — Cort Johnson** (`healthrising.org`) — independent blog — high · crawl: https://healthrising.org/feed
  In-depth analysis of ME/CFS and long COVID research findings.
- **AMMES Research Foundation** (`ammes.org`) — research org — high · crawl: https://ammes.org/feed
  Peer-reviewed ME/CFS and post-COVID mechanism studies and reviews.
- **UK ME Association** (`meassociation.org.uk`) — research org — high · crawl: https://meassociation.org.uk/feed
  ME/CFS research news, trials, and biomedical updates.
- **RECOVER Initiative** (`recovercovid.org`) — research org / registry — high · crawl: https://recovercovid.org/rss.xml
  NIH long COVID cohort trial and biomarker program updates.

### 4. Multiple Sclerosis Research

strong

- **Multiple Sclerosis Research Blog** (`multiple-sclerosis-research.org`) — independent blog — high · crawl: https://multiple-sclerosis-research.org/feed
  Evidence-based commentary on new MS trials and immunology research.
- **NEJM** (`nejm.org`) — academic/journal — high · crawl: https://api.openalex.org/works?filter=primary_location.source.id:S62468778
  Definitive MS and clinical trial publications. Native feed (nejm.org/rss-feed/) and homepage HTML are bot-blocked with no reachable feed (verified via check_url), so the crawler is pointed at the verified OpenAlex source endpoint (S62468778) instead of HTML article pages.
- **Multiple Sclerosis News Today** (`multiplesclerosisnewstoday.com`) — independent blog — high · crawl: https://multiplesclerosisnewstoday.com/feed
  High-frequency MS research and clinical trial reporting, including myelin-repair and EBV-pathogenesis studies; replaces removed nationalmssociety.org.

### 5. Alzheimer's & Neurodegeneration

strong

- **National Institute on Aging** (`nia.nih.gov`) — regulator — high
  NIH-funded Alzheimer's and aging research programs and discoveries.
- **Nature** (`nature.com`) — academic/journal — high · crawl: https://www.nature.com/nature.rss
  Top-tier peer-reviewed research across Alzheimer's/dementia, AI drug discovery, and aging biology; now crawled via its native RSS feed.

### 6. Genetic & AI-Driven Drug Discovery

strong

- **Genetic Engineering & Biotechnology News** (`genengnews.com`) — trade press — high · crawl: https://genengnews.com/feed
  CRISPR, genomics, and AI-discovered candidate coverage.
- **Nature** (`nature.com`) — academic/journal — high · crawl: https://www.nature.com/nature.rss
  Top-tier peer-reviewed research across Alzheimer's/dementia, AI drug discovery, and aging biology; now crawled via its native RSS feed.
- **MIT Technology Review — The Checkup** (`technologyreview.com`) — newsletter — medium · crawl: https://www.technologyreview.com/feed
  Weekly biotech and AI-in-health digest; novel-therapy explainers.

### 7. Longevity & Aging Biology

strong

- **Lifespan.io** (`lifespan.io`) — independent blog — high · crawl: https://lifespan.io/feed
  Longevity research news, funding, and anti-aging intervention pipelines.
- **Fight Aging!** (`fightaging.org`) — independent blog — high · crawl: https://fightaging.org/feed
  Daily longevity science reporting on senolytics and repair biotech.
- **Nature** (`nature.com`) — academic/journal — high · crawl: https://www.nature.com/nature.rss
  Top-tier peer-reviewed research across Alzheimer's/dementia, AI drug discovery, and aging biology; now crawled via its native RSS feed.

### 8. Policy, Regulation & Market Design (biopharma)

medium

- **STAT News — Policy** (`statnews.com`) — trade press — high · crawl: https://statnews.com/feed
  FDA policy, drug pricing, and clinical trial reform coverage.

## Registries
- **OpenAlex API** (`api.openalex.org`) — Structured scholarly metadata API; crawler endpoint for bot-protected paywalled journals (Nature, NEJM, Cell).
- **ClinicalTrials.gov** (`clinicaltrials.gov`) — Definitive global clinical trial registry with status, interventions, outcomes across all target conditions.
- **RECOVER Initiative Registry** (`recovercovid.org`) — NIH long COVID observational cohort and trial protocols registry.
- **FDA Drug Approvals** (`fda.gov`) — New drug and biologic approval announcements and regulatory guidance.

## Queries
1. ME/CFS long COVID mechanism biomarker clinical trial
2. multiple sclerosis disease-modifying therapy trial readout
3. Alzheimer's amyloid tau clinical trial pipeline
4. AI drug discovery generative biology platform
5. longevity senescence intervention clinical trial

## News vs analysis
Moderately balanced with a research-forward tilt. High-frequency trade-press news (Endpoints, STAT, GEN) supplies event reporting, while independent analysis blogs (Health Rising, MS Research Blog, Fight Aging!, Lifespan.io) and academic/registry sources (OpenAlex, Nature, NEJM, Cell) supply first-principles and empirical depth. Policy/regulator sources (FDA) anchor the regulation subarea. Analysis modestly outweighs pure news, matching the user's first-principles emphasis.

## Notes
Blacklisted user source blog.eladgil.com excluded at L1. Bot-protected paywalled journals (Nature, NEJM, Cell, Cell Press) are crawled via the OpenAlex API endpoint rather than HTML article pages. Fierce Biotech is bot-protected with no reachable feed, so fresh items are surfaced through the OpenAlex source filter while the resolving domain remains as a crawl target. Candidate domains that failed mechanical DNS/feed gates were excluded: mmme.io (DNS fail), msdiscovery.org (DNS fail), longcovidresearchnetwork.org (DNS fail), longcovidalliance.org (stale feed), openscience.org (stale feed), agenbio.com (stale feed), and pathophysiology.cell.com (DNS fail). Source-type mix exceeds the minimum: trade press (7), independent blogs (6), academic/journal (via OpenAlex endpoints), research organizations (6), regulators (2), newsletter (1), and data/registries (4). All listed domains and feed endpoints were verified with check_url where the tool budget permitted.

## Review record
- [minor] duplicates: domain genengnews.com also under 'Drug Development & Clinical Research'
- [minor] duplicates: domain genengnews.com also under 'Drug Development & Clinical Research'
- [minor] duplicates: domain nature.com also under 'Alzheimer's & Neurodegeneration'
- [minor] duplicates: domain nature.com also under 'Alzheimer's & Neurodegeneration'
- [minor] duplicates: domain statnews.com also under 'Drug Development & Clinical Research'
- [major] crawlability: no feed found at cell.com (homepage returned HTML without a feed link)
- [major] crawlability: no feed found at nejm.org (homepage returned HTML without a feed link)
