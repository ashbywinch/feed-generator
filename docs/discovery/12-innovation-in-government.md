# Innovation in Government — Discovery Source List

Status: needs-human by reviewer loop (iteration 3). 8 subareas, 16 sources, 5 queries. Generated 2026-08-03.

## Subareas
### 1. Government as a Platform / GOV.UK core platform

strong

- **GDS blog** (`gds.blog.gov.uk`) — regulator blog — high · crawl: https://gds.blog.gov.uk/feed
  Official Government Digital Service blog: GOV.UK One Login, GOV.UK app, Service Standard evolution — the heart of the platform subarea.
- **CDDO blog** (`cddo.blog.gov.uk`) — regulator blog — high · crawl: https://cddo.blog.gov.uk/feed
  Central Digital and Data Office — cross-government digital/data strategy, legacy IT modernisation and the '20 systems' mission.
- **PublicTechnology** (`publictechnology.net`) — trade press — high · crawl: https://publictechnology.net/feed
  UK govtech trade press covering GDS moves, One Login rollout, central digital programmes and platform decisions.

### 2. Service design & design systems

strong

- **State of Digital Publishing** (`stateofdigitalpublishing.com`) — independent blog — medium · crawl: https://stateofdigitalpublishing.com/feed
  Independent senior-digital-leader blog on service design, content strategy and publishing practice inside public-sector and health organisations.
- **PublicTechnology (service design coverage)** (`publictechnology.net`) — trade press — high · crawl: https://publictechnology.net/feed
  Reports service standard evolution and user-centred design adoption across government departments.

### 3. Policy innovation & Policy Lab practice

good

- **Institute for Government** (`instituteforgovernment.org.uk`) — think tank — high · crawl: https://instituteforgovernment.org.uk/rss
  IfG publishes landmark reports and commentary on digital transformation of public services and management of digital government.

### 4. Civil service digital transformation & skills

good

- **Civil Service blog** (`civilservice.blog.gov.uk`) — regulator blog — high · crawl: https://civilservice.blog.gov.uk/feed
  Civil Service Leadership blog tracks DDaT profession, digital capability framework and transformation programmes across departments.
- **The Register — Public Sector** (`theregister.com`) — trade press — high · crawl: https://api.theregister.com/api/v1/article?orderBy=published&site_id=2&remapper=rss
  Independent tech press with dedicated public-sector coverage: legacy IT failures, digital identity rollout and Whitehall tech projects.

### 5. Digital identity / One Login

good

- **GDS blog (One Login updates)** (`gds.blog.gov.uk`) — regulator blog — high · crawl: https://gds.blog.gov.uk/feed
  Authoritative for GOV.UK One Login / GOV.UK Verify replacement programme details and digital identity rollouts.
- **PublicTechnology** (`publictechnology.net`) — trade press — high · crawl: https://publictechnology.net/feed
  Tracks political and policy decisions affecting the national digital identity rollout.

### 6. Local government digital

moderate

- **PublicTechnology (local government)** (`publictechnology.net`) — trade press — high · crawl: https://publictechnology.net/feed
  Covers council digital transformation and shared-services programmes.
- **Socitm (Society for Innovation, Technology and Modernisation)** (`socitm.net`) — independent blog / membership body — high · crawl: https://socitm.net/feed
  UK membership body for public-service technology leaders — council digital transformation, service design and shared-services analysis from the local government perspective.
- **Digital Luton** (`luton.localgov.blog`) — independent blog — high · crawl: https://luton.localgov.blog/feed
  Council digital team blog with working RSS — practical service design and digital delivery lessons from local government.

### 7. International digital government

moderate

- **FedScoop** (`fedscoop.com`) — trade press — high · crawl: https://fedscoop.com/feed
  US federal government tech news: digital platform strategy, FedRAMP, govtech modernisation and AI adoption — direct US comparison to UK GDS, with a working RSS feed.

### 8. Open data, transparency & data sharing

good

- **Chosen Path (Owen Boswarva)** (`chosen-path.org`) — independent blog — medium · crawl: https://chosen-path.org/feed
  Long-running independent commentary on UK government data policy, transparency and FOI — first-principles analysis of data infrastructure.
- **Data in government (GDS/analysis)** (`dataingovernment.blog.gov.uk`) — regulator blog — high · crawl: https://dataingovernment.blog.gov.uk/feed
  GDS data science and analysis team blog — practical data policy, performance analysis and data sharing inside government; working RSS feed replacing the bot-blocked ODI for this subarea.

## Registries
- **GOV.UK Find and update open data** (`data.gov.uk`) — Official UK government open data portal — machine-readable datasets on public services, spend and transformation.
- **GOV.UK Digital Marketplace (G-Cloud / DOS)** (`digitalmarketplace.service.gov.uk`) — National registry of digital services and frameworks — reveals government's supplier ecosystem for platform and service delivery.
- **ONS** (`ons.gov.uk`) — Office for National Statistics data on government digital service uptake, internet use and digital inclusion baselines.
- **OpenAlex** (`api.openalex.org`) — Open scholarly index API for discovering peer-reviewed research on digital government, e-gov and public-sector innovation.

## Queries
1. GOV.UK One Login rollout departments timetable
2. Central Digital and Data Office legacy systems mission progress
3. UK government digital service transformation case study 2025
4. Digital government platform policy Institute for Government report
5. open data digital public services UK transparency

## News vs analysis
{'news': ['publictechnology.net', 'theregister.com', 'govinsider.asia', 'gds.blog.gov.uk', 'cddo.blog.gov.uk'], 'analysis': ['instituteforgovernment.org.uk', 'theodi.org', 'chosen-path.org', 'stateofdigitalpublishing.com']}

## Notes
UK-centric per the topic's `in` scope (DWP/HMRC/GDS/design systems). Subscribed blog.gov.uk domains (GDS platforms, Policy Lab, user research, department digital teams) are blacklisted; the GDS main blog and CDDO blog are distinct non-blacklisted domains and are retained as core signals. Trade press falls back to free headline feeds (crawl_root given) for paywalled articles. Topic's 'out' boundaries respected: no party politics or general public-services commentary.

## Review record
- [major] schema: news_vs_analysis is not a string
- [minor] duplicates: domain publictechnology.net also under 'Government as a Platform / GOV.UK core platform'
- [minor] duplicates: domain gds.blog.gov.uk also under 'Government as a Platform / GOV.UK core platform'
- [minor] duplicates: domain publictechnology.net also under 'Government as a Platform / GOV.UK core platform'
- [minor] duplicates: domain publictechnology.net also under 'Government as a Platform / GOV.UK core platform'
