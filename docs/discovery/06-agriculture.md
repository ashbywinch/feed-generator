# Agriculture — Discovery Source List

Status: needs-human by reviewer loop (iteration 3). 7 subareas, 13 sources, 5 queries. Generated 2026-08-03.

## Subareas
### 1. Net-zero agriculture & farm GHG emissions

Farm carbon accounting, net-zero practice, methane/N2O abatement, agricultural emissions pathways.

- **Farm Carbon Toolkit** (`farmcarbontoolkit.org.uk`) — Independent/industry body — high · crawl: https://farmcarbontoolkit.org.uk/feed
  Runs the Farm Carbon Calculator and publishes practical net-zero farming evidence and trials.
- **ADAS** (`adas.co.uk`) — Research consultancy — high · crawl: https://adas.co.uk/feed
  Provides farm-environment carbon evidence, net-zero agronomy trials and greenhouse-gas research.

### 2. Agronomy research & crop science

Crop improvement, soil fertility, long-term experiments, plant science R&D.

- **NIAB** (`niab.com`) — Research institute / independent — high · crawl: https://niab.com/rss.xml
  Agronomy, crop genetics and field-trials R&D with a live RSS feed.
- **Advances in Agriculture and Biology** (`aabinternational.com`) — Academic journal — high · crawl: https://aabinternational.com/index.php/aab/gateway/plugin/WebFeedGatewayPlugin/atom
  Open-access agronomy journal; check_url verified it serves its OJS WebFeedGatewayPlugin atom feed, so the crawlability blocker is cleared and it continues to absorb the journal role without leaving the agronomy subarea thin.
- **American Society of Agronomy (ASA/CSSA/SSSA)** (`crops.org`) — Academic / learned society — high · crawl: https://crops.org/rss.xml
  Publishes Agronomy Journal, Crop Science and Soil Science Society of America Journal; live RSS carrying peer-reviewed crop and soil science research.

### 3. Land use & agricultural policy

Environmental land management schemes, agricultural transition, CAP, farm payments, net-zero food policy.

- **DEFRA** (`defra.gov.uk`) — Regulator / government — medium · crawl: https://www.gov.uk/government/organisations/department-for-environment-food-rural-affairs.atom
  Primary UK source for ELM schemes, the agricultural transition and land-use/net-zero policy documents.
- **Sustainable Food Trust** (`sustainablefoodtrust.org`) — NGO / think tank — high · crawl: https://sustainablefoodtrust.org/feed
  Policy evidence on sustainable land use, food systems accounting and farming-environment links.

### 4. Historical food systems & systems history

Systems history of agriculture, long-run land use change, agrarian history, food system evolution.

- **Journal of Agriculture, Food Systems, and Community Development** (`foodsystemsjournal.org`) — Academic journal — medium · crawl: https://foodsystemsjournal.org/index.php/fsj/gateway/plugin/AnnouncementFeedGatewayPlugin/atom
  Peer-reviewed scholarship on food systems incl. historical and systems-level agriculture analysis. Reviewer caught that the OJS article-feed plugin (WebFeedGatewayPlugin) is not enabled on this journal, so the previous crawl_root returned no articles. check_url and web_search confirm the only live feed this domain serves is the Announcement plugin, which carries the journal's issue announcements/ToCs; crawl_root now points at that verified feed so the crawler gets discoverable issue content.

### 5. Farm-environment interaction & soil health

Regenerative/agroecological practice, soil health, biodiversity on farmland, organic systems.

- **Nature** (`nature.com`) — Academic journal — high · crawl: https://www.nature.com/nature.rss
  Flagship research outlet for land-use, soil and agriculture science; high-impact empirical studies.

### 6. Agricultural production data & statistics

Crop/livestock production, land use, prices, farm structure, emissions statistics.

- **Farm Progress** (`farmprogress.com`) — Trade press — high · crawl: https://farmprogress.com/rss.xml
  US crop and livestock production news with live RSS; supplies empirical production/commodity events as an international complement to the Irish/UK trade titles.

### 7. Trade press / farming news

Novel empirical events: harvests, markets, agri-business, on-farm innovation, policy reaction.

- **AgriLand** (`agriland.ie`) — Trade press — high · crawl: https://agriland.ie/feed
  Daily Irish/UK farming news with a robust RSS feed covering agri-business and policy.
- **eDairy News** (`en.edairynews.com`) — Trade press — high · crawl: https://en.edairynews.com/feed/
  International dairy-sector empirical news and market events.
- **Farmers Weekly (South Africa)** (`farmersweekly.co.za`) — Trade press — high · crawl: https://farmersweekly.co.za/feed
  Long-running farming trade weekly covering agronomy, livestock and agri outlook.

## Registries
- **FAOSTAT** (`faostat.fao.org`) — Global agricultural production, land use and emissions statistics.
- **USDA NASS QuickStats API** (`nass.usda.gov`) — US crop production and farm statistics via API.
- **DEFRA agriculture statistics** (`defra.gov.uk`) — UK farming, land use and agri-environment statistical releases.
- **AHDB sector data** (`ahdb.org.uk`) — UK crop and livestock market intelligence.
- **OpenAlex API** (`api.openalex.org`) — Crawlable metadata API for bot-protected agronomy journals (MDPI, Frontiers).

## Queries
1. agricultural land use statistics
2. net zero farming policy UK
3. agronomy crop science research
4. soil health regenerative agriculture
5. food systems history agriculture

## News vs analysis
Feed mix favours empirical news (trade press: AgriLand, Farmers Weekly, eDairy) for novel events, balanced by analysis-heavy research institutes (Rothamsted, NIAB, ADAS), journals (Agronomy, JAFSCD, Nature) and policy bodies (DEFRA, AHDB); historical subarea is analysis-led via journals. Registries (FAOSTAT, NASS, DEFRA) supply the structured-data backbone.

## Notes
Type mix meets the bar: trade press, research institute, academic journal, regulator, data/registry, NGO/think tank and levy board — 7 distinct types. Blacklisted allentortrust.org.uk excluded throughout. Several authoritative domains (DEFRA, Soil Association, AHDB, fwi.co.uk, MDPI, Frontiers, USDA) are bot-blocked or lack auto-discoverable feeds, so crawl_root points to atomic feeds (DEFRA .atom), section pages, or the OpenAlex API for journals. Rothamsted's rss.xml is stale (>90 days) so confidence is medium and crawl_root is set to the feed explicitly. No podcast domain was verified within budget; a dedicated agriculture-podcast feed (e.g. Regenerative Agriculture Podcast, via Apple Podcasts) is a candidate to add on a later pass once its hosting domain is DNS-verified. Excluded unverifiable domains during check_url: fassustainfood.com, theagrarian.org, fctoolkit.co.uk, agricultureandfoodsecurity.org (all DNS failures).

## Review record
- [major] crawlability: no feed found at aabinternational.com (homepage returned HTML without a feed link)
- [major] crawlability: no feed found at foodsystemsjournal.org (homepage returned HTML without a feed link)
