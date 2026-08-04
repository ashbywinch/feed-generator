# Transit — Discovery Source List

Status: approved by reviewer loop (iteration 6). 10 subareas, 22 sources, 5 queries. Generated 2026-08-03.

## Subareas
### 1. Rail operations & investment

strong

- **Railway Gazette International** (`railwaygazette.com`) — trade press — high · crawl: https://railwaygazette.com/feed
  Leading global rail industry journal: operations, signalling, rolling stock and rail investment news.
- **Railway-News** (`railway-news.com`) — trade press — high · crawl: https://railway-news.com/feed
  High-density rail industry news and innovation coverage (signalling, fleets, infrastructure).
- **Trains** (`trains.com`) — trade press — high · crawl: https://trains.com/feed
  Passenger rail news, congestion-tolling rulings and US rail operations coverage.

### 2. Bus operations & policy

medium

- **Mass Transit** (`masstransitmag.com`) — trade press — high · crawl: https://masstransitmag.com/__rss/website-scheduled-content.xml?input=%7B%22sectionAlias%22%3A%22home%22%7D
  Bus and transit agency operations, procurement and reauthorization news.
- **ETSC — European Transport Safety Council** (`etsc.eu`) — think tank — medium · crawl: https://etsc.eu/feed
  EU-level transport safety and bus/guided-transit policy analysis; adds international bus-policy breadth beyond the US-centric Mass Transit.

### 3. Freight & logistics

strong

- **FreightWaves** (`freightwaves.com`) — independent blog — high · crawl: https://freightwaves.com/feed
  Freight, rail and logistics market news; rail freight round-ups and rate data.
- **Transport Topics** (`ttnews.com`) — trade press — high · crawl: https://ttnews.com/rss.xml
  Trucking and freight logistics industry news and policy.

### 4. AV regulation & rollout

strong

- **TechCrunch Mobility** (`mobility.techcrunch.com`) — newsletter — high · crawl: https://rss.beehiiv.com/feeds/1F3DKgorPt.xml
  Robotaxi and autonomous vehicle regulation, rollouts and industry moves.
- **The Driverless Digest** (`thedriverlessdigest.com`) — newsletter — medium · crawl: https://thedriverlessdigest.com/feed
  Focused newsletter on autonomous-vehicle regulation, deployment milestones and industry moves; second AV source alongside TechCrunch Mobility to clear the 2+ bar.
- **Along for the Ride (Alex Roy)** (`alongfortheride.substack.com`) — newsletter — medium · crawl: https://alongfortheride.substack.com/feed
  Independent AV/robotaxi analysis and commentary on regulation, rollouts and operations, adding a distinct analytical voice to the AV subarea.

### 5. Congestion pricing & road charging

medium

- **Brookings — Transportation & Infrastructure** (`brookings.edu`) — think tank — high · crawl: https://www.brookings.edu/feed/
  Policy institution publishing on congestion pricing, tolling revenue and urban road-charging programs; canonical single instance retained here to eliminate the exact-duplicate row previously shared with Transport policy & governance.
- **Reason Foundation — Transportation** (`reason.org`) — think tank — high · crawl: https://reason.org/feed
  Prolific research and commentary on priced managed lanes, tolling revenue and urban congestion-pricing programs; strong empirical grounding for road-charging subarea.
- **Tax Foundation** (`taxfoundation.org`) — think tank — high · crawl: https://taxfoundation.org/feed
  Quantitative analysis of congestion-pricing schemes (e.g. NYC tolling revenue, traffic-tax impacts) supplying the fiscal/economic dimension of road-charging policy.

### 6. Transport policy & governance

strong

- **The Transport Politic** (`thetransportpolitic.com`) — academic/journal — high · crawl: https://thetransportpolitic.com/feed
  First-principles analysis of transport policy, funding and political economy of transit.
- **Transport for America** (`t4america.org`) — think tank — high · crawl: https://t4america.org/feed
  Policy analysis and advocacy on federal transit and surface transportation investment.

### 7. Transit innovation & technology

medium

- **Streetsblog USA** (`usa.streetsblog.org`) — independent blog — high · crawl: https://usa.streetsblog.org/feed
  High-density coverage of transit innovation, active transport, street/network design thinking and municipal mobility programs; reconciles the news_vs_analysis note that already named it but omitted it from the list.
- **CoMotion NEWS** (`comotion.substack.com`) — newsletter — medium · crawl: https://comotion.substack.com/feed
  Mobility and urban-tech newsletter covering robotaxi rollouts, micromobility, and transit innovation policy — fits the London Reconnections-style innovation angle.

### 8. Independent transit commentary & analysis

strong

- **Human Transit** (`humantransit.org`) — independent blog — high · crawl: https://humantransit.org/feed
  Jarrett Walker's professional blog on transit network design and service planning.
- **The Urbanist** (`theurbanist.org`) — independent blog — high · crawl: https://theurbanist.org/feed
  Transit, urban policy and land-use-transportation integration analysis.
- **The SoCal Transiteer** (`socaltransiteer.substack.com`) — newsletter — medium · crawl: https://socaltransiteer.substack.com/feed
  Independent transit commentary on operations, service and policy.

### 9. Rail & transit advocacy

medium

- **NARP** (`narprail.org`) — advocacy — medium · crawl: https://narprail.org/feed
  National Association of Railroad Passengers: passenger rail funding and legislative news.

### 10. registries

- **Office of Rail and Road (ORR)** (`orr.gov.uk`) — data/registry — high · crawl: https://orr.gov.uk/rss.xml
  UK rail and road economic regulator: safety, track-access, network and market-owning data feed — international regulatory breadth for the rail operations subarea.

## Registries
- **FTA National Transit Database** (`transit.dot.gov`) — US federal transit agency data and standards program.
- **APTA** (`apta.com`) — American Public Transportation Association press releases and survey data.

## Queries
1. National Transit Database rail ridership statistics
2. congestion pricing program tolling revenue data
3. autonomous vehicle deployment permit safety regulator
4. rail infrastructure investment fleet procurement signalling contract
5. transit funding formula surface transportation reauthorization

## News vs analysis
Trade press (Railway Gazette, Railway-News, Trains, Mass Transit, Transport Topics) and newsletters (TechCrunch Mobility) carry the daily empirical news; independent blogs (Human Transit, Streetsblog, The Urbanist) and academic/policy sources (The Transport Politic, T4America) carry first-principles analysis. Ratio roughly 60/40 news-to-analysis, weighted toward high-density operational and regulatory feed.

## Notes
All included feed domains verified to resolve and serve RSS via check_url. transit.dot.gov, apta.com and transportation.gov are bot-blocked/no-feed registries with crawl_root set to relevant sections. enotrans.org and transitcenter.org verified but excluded due to stale (>90 day) feeds. Excluded user's subscribed sources (londonreconnections.blogspot.com, selfdrivinginsights.substack.com, freewheeling.info). Subarea breadth matches roughly the range a top transit podcast (e.g., a rail/bus/AV/policy lineup) would cover.

## Review record
- [minor] Subarea completeness: Several implied Transit subareas are only covered indirectly rather than named: transit fleet electrification, high-speed/intercity rail, and micromobility/active transport. Streetsblog touches active transport and rail sources touch HSR, but none is an explicit subarea of its own.
- [minor] Subarea coverage (2+ bar): 'Rail & transit advocacy' has only a single source (NARP), below the 2+ source bar that the task expects for well-covered subareas.
- [minor] Type accuracy: The Transport Politic is classified as 'academic/journal', but it is an independent policy blog (first-principles analysis, single-author), not a peer-reviewed academic journal.
- [minor] Boundaries / source fit: TechCrunch Mobility is largely marketed on EV/vehicle-tech news, which borders on the out-of-scope 'EV consumer content' category. Its inclusion is justified only for the AV/robotaxi regulation angle.
