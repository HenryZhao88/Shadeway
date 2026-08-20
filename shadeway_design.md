# shadeway design notes

what this is: everything we decided, why, and what to build. written loose on purpose. read top to bottom once, then use it as reference.


## what we locked in

one flagship city, new york, manhattan plus brooklyn

thermal output is "feels like" degrees celsius, not percent shaded and not kilojoules. we compute mean radiant temperature and then run utci on it.

team is 2 to 4 people who know python and typescript/react.

shade is computed by runtime ray casting against a scene, not baked ahead of time. this means we need a server. that is fine and it buys us things (see below).

all four headline features are in scope. shaded side of street guidance, departure time optimizer, personal heat profile, cool waypoints and rest stops. plus the shadow time scrubber which was always assumed.


## why this isn't a rehash

there is real prior art. coolwalks in barcelona (2021) with its "vampire mode", the coolwalks paper in nature scientific reports, shaderoute from acm 2025, asu's cool routes, shademap.app. so "shadiest walking route" as a concept is taken.

but every single one of them treats shade as binary. pixel is either sunny or shaded. and none of them model the sun moving while you walk.

we do two things none of them do:

first, we output a felt temperature in degrees. "this route feels like 41, the cool one feels like 33" is a sentence a human already understands. "62 percent shaded" is not. that number is why a public health person will take us seriously and why a judge will get it in two seconds.

second, the sun moves during the walk. a 40 minute walk starting at 3pm ends at 3:40 and the shadows are different. the sun moves about 15 degrees of azimuth per hour so over a typical walk this genuinely changes which route wins. once you model that, the departure time optimizer basically falls out for free, and nobody else has it.

third thing, smaller but very demoable: because we build left and right sidewalks as separate edges, we can say "cross to the east side of 5th ave at 42nd". google maps structurally cannot say that. it routes on street centerlines.


## the data

all of this is nyc open data, all free, no api keys anywhere.

street centerline (cscl). this is the routable network. it is properly connected with real topology. this is our graph skeleton.

sidewalk centerline. 120,316 features citywide, i checked. important catch though: the nyc planimetrics capture rules confirm crosswalks are NOT captured, and intersection connectivity is undocumented. so this is not routable out of the box. do not try to build the graph from it.

what we do instead: build the graph from cscl, split every street segment into a left and a right sidewalk edge by offsetting the centerline, then synthesize crossing edges at each intersection. use the planimetric sidewalk data to sanity check the offsets and to recover actual sidewalk widths. we get guaranteed connectivity and per side edges at the same time.

building footprints with heightroof, derived from lidar. these are our occluders.

2015 street tree census. 666,134 trees mapped, about 652,169 after cleaning. every tree has lat, lon, species, diameter at breast height, and health. this is the good stuff. more on it below.

tree canopy raster at 6 inch resolution from lidar. use this as ground truth to check that our tree crown modelling isn't producing nonsense.

8 class landcover raster from the same lidar. gives us ground albedo (asphalt vs concrete vs grass) which we need for the reflected shortwave term.

drinking fountains, cooling centers, park entrances. for the waypoints feature.

heat vulnerability index by neighborhood. good for the pitch, optional for the product.

weather comes from open meteo. i tested it live. it returns access control allow origin star so the browser can hit it directly, no key, no proxy. the variables we need are all there: temperature_2m, relative_humidity_2m, wind_speed_10m, cloud_cover, direct_normal_irradiance, diffuse_radiation, shortwave_radiation, uv_index. sample pull for times square at 3pm gave 30.6 degrees, dni 799 W/m2, diffuse 148 W/m2, cloud cover 6 percent. that is exactly what the thermal model eats.

we will still cache weather on the server rather than letting the client hammer it, but the fact that it works from a browser means we have a zero infrastructure fallback if the server dies on demo day.


## system shape

four units. each one testable on its own, none of them reaching into another's guts.

occluderfield. answers "is this point in sun right now, and how much sky can it see". input is a list of points plus sun azimuth and elevation. output is f_sun (fraction of direct beam getting through) and svf (sky view factor). depends only on scene geometry.

thermalmodel. answers "given radiation and geometry, what does it feel like". input is f_sun, svf, and the weather. output is degrees. this is pure functions with no state and no io, which matters because it's the piece a judge might poke at, so it should be the piece with the best tests.

router. answers "cheapest paths under a time versus heat tradeoff". input is origin, destination, departure time. output is a set of routes on the pareto frontier. depends on the graph plus a cost callback, and knows nothing about physics.

web. renders and lets you poke at it. talks rest. knows nothing about anything.

data flows: pipeline (python, offline, on your laptop) produces scene and graph files. server (fastapi) loads them and runs occluderfield, thermalmodel, router. web (react plus deck.gl) calls the server for routes and draws its own shadows on the gpu.


## the geometry engine

the big realization: you do not need 3d ray casting for this.

buildings are vertical prisms. tree crowns are blobs sitting at a known height. so every shade test collapses to 2d.

a pedestrian point p at 1.1 meters. sun at azimuth phi, elevation h. shoot a 2d ray from p in direction phi across the plan view. for every building the ray crosses at plan distance d with height H, it blocks if H is greater than 1.1 plus d times tan(h). that's it. one strtree query for what the ray crosses, one comparison per hit. no mesh, no bvh, no 3d math at all.

shapely 2.0 has a vectorized strtree that does this in roughly microseconds per ray.

cap the ray at about 400 meters. at low sun angles a tall building technically blocks much further than that, but at low sun the direct normal irradiance is small anyway so the error barely moves the felt temperature.


## trees, which is where the fidelity actually lives

buildings are easy because they're opaque. trees are not opaque and that's the interesting part.

model a crown as a circle in plan with a base height, a top height, and a transmissivity tau. tau is how much direct beam gets through the leaves.

the census gives us species and trunk diameter for every tree. from species we get tau, because leaf density is a species property. honey locust is famously airy, something like 0.35. london plane is dense, maybe 0.15. callery pear denser still. from diameter at breast height we get crown radius and tree height via published urban allometric equations (i tree has these, look them up during the build, do not make them up).

then cross check the whole thing against the 6 inch canopy raster. if our modelled crowns don't roughly cover where the raster says canopy is, our allometry is wrong.

payoff is a line nobody else can say: "this block is shaded but they're honey locusts, you'll get dappled light not real shade." that one sentence proves to a judge that we actually understand the domain instead of just drawing polygons.

be honest in the doc and the demo: the tau values above are my estimates. get real ones from literature during the build.


## the horizon cache, which is how ray casting stops being slow

the one real risk with runtime ray casting is a cold cache during the live demo. here's how we kill it.

when the router first touches an edge, do not cast one ray. cast 72 of them, one per 5 degrees of azimuth, at each sample point along the edge. store the resulting horizon profile, which is just "what is the highest obstruction angle in each direction". keep two of them, one for opaque buildings and one for tree canopy, because they behave differently.

so the cache is roughly horizon[edge_id] as a uint8 array shaped 2 by number of samples by 72.

that costs about 3 milliseconds the first time. after that, every time of day and every date for that edge is an o(1) array lookup with a bit of interpolation between bins. the sun's position is just an index.

three nice consequences.

one, sky view factor comes off the exact same array for free. svf equals 1 minus the mean of sin squared beta, where beta is the horizon angle in each bin. we need svf anyway for the longwave terms in the thermal model, so this is a real saving not a trick.

two, warming the cache is just an optimization flag, not a separate system. "make warm" walks every edge through the identical code path. about 3 minutes for manhattan plus brooklyn. run it before the demo and the cold cache risk is gone, but nothing in the architecture depends on having run it. same code either way.

three, the scene stays mutable. planting trees invalidates only the cache entries whose sample points are within the affected radius. everything else stays warm. so "plant 40 trees on this corridor and re run" is a real feature and not a rebuild.

also worth noticing: because this runs on a server there is no download budget. that means we keep full per sample point resolution, roughly a sample every 10 meters, instead of averaging down to one number per edge. about 69 megabytes of server ram for both boroughs. that's nothing. a browser only design would have forced us to compress that away.


## about the scrubber lagging

three different things were hiding behind the word "scrubber" and only one of them actually needs the server.

the city shadows on the map. that's gpu, client side, deck.gl sunlight. instant, and it never touches the server at all.

the route's heat versus time curve. one server call returns the whole time series for the currently displayed route. instant after the first load, because it's the same sample points evaluated at n different times, which the horizon cache makes almost free.

the actual re route. this is the only thing that genuinely needs a round trip. debounce it, about 150 milliseconds. and honestly a slight lag on re route reads as "it's thinking" rather than "it's broken".


## the thermal model

this is the solweig lite chain. geometry and weather in, degrees out.

inputs per sample point per instant:
Ib is direct normal irradiance from open meteo, W/m2.
Id is diffuse radiation, W/m2.
Ig is global horizontal shortwave, W/m2.
Ta is air temperature in celsius.
RH is relative humidity percent.
v is wind speed, from 10 meters, adjusted down to pedestrian height around 1.1 meters.
svf is sky view factor from the horizon profile.
f_sun is fraction of direct beam reaching the person. 1 if fully open, tau if under canopy, 0 if a building blocks it.
ground and wall albedo from the landcover raster.

shortwave side:
direct on the body is f_sun times Ib times a projected area factor that depends on solar elevation.
diffuse is svf times Id.
reflected is the non sky portion times wall albedo times Ig, plus a ground reflection term.

longwave side:
from sky, svf times sky emissivity times sigma times absolute air temp to the fourth. sky emissivity from a standard clear sky formula with a cloud correction.
from surfaces, the non sky portion times surface emissivity times sigma times absolute surface temp to the fourth. surface temp is air temp plus a solar driven bump, roughly plus 10 to 20 for sunlit surfaces and plus 0 to 3 for shaded ones.

then combine all six directions with angular weighting factors and solve for mean radiant temperature, tmrt.

then utci from air temp, tmrt, wind speed, and humidity, using the standard sixth order polynomial approximation. about 210 terms of published coefficients. deterministic and fast.

important honesty note: i could not verify fanger's projected area factor or the six directional angular weights to exact numbers from a source i trust. the structure of the model is standard and correct. the constants need to be read out of the solweig manual or umep source during implementation. do not take them from memory, mine or anyone's. this is a concrete task, not a hole in the design.

speed trick worth doing: the utci polynomial is expensive to call per edge per label during a graph search. but air temp, humidity, and wind are essentially uniform across the city at a given hour. so for each timestep, precompute utci as a one dimensional curve over tmrt only, sampled every half degree. then the hot path is a table lookup plus a lerp instead of 210 terms. this is a big win and costs about ten lines.

testing: this unit gets golden value tests against published solweig and utci reference numbers. it's pure functions so this is easy and it's the highest value testing in the whole project.


## the router

the honest formulation of the problem: cost of an edge depends on what time you arrive at it, and what time you arrive depends on how long the path so far was, which is part of what you're optimizing. that's a time dependent shortest path with a second objective stapled on.

three ways to handle it, in increasing order of correctness.

the lazy way: freeze the sun at departure time for the whole trip. wrong, but it's what everyone else does.

the fixed point way: route with the sun at departure time, get an estimated arrival time at every node, re route using those per node times, repeat two or three times. converges fast because the sun moves slowly compared to a walk. easy to explain and correct enough.

the good way, and what i'd build: bicriteria label setting, martins style. keep the pareto frontier of (time, heat) at each node instead of a single best label. this gives you the entire tradeoff curve in one search, which is exactly the product concept. resolve the time dependence with the fixed point iteration on top.

why this is worth it: once you have the pareto frontier, the personal heat profile stops being a re route and becomes a display choice. the slider "how much extra time will you spend" just picks a different point on a frontier you already computed. same for the whole route comparison ui. it all becomes instant.

to stop the label count exploding, use epsilon dominance pruning: round the heat cost into buckets of about 0.1 degree minutes before comparing labels. completely standard, keeps things fast, and the error is invisible.


## how the four features fall out

shaded side of street. the graph already has left and right sidewalks as separate edges, so the router picks a side without any extra work. the only new code is turning a side change into an instruction, "cross to the east side of 5th ave at 42nd". then annotate why: west side is in full sun until 6:40, east side is shaded by 500 fifth, difference on this block is about 5 degrees.

departure time optimizer. sweep departure time in 15 minute steps across the next few hours and re run the search for each. they're independent so run them in parallel. render as a curve of felt temperature against departure time with a marker on now and a marker on best. "wait 38 minutes, be 7 degrees cooler." the horizon cache is what makes this cheap, because all those runs hit the same warm edges.

personal heat profile. age, medical heat sensitivity, outdoor worker, walking pace, all collapse into one number: how many extra minutes is one degree worth. standard maybe 1 minute per degree, sensitive 3, high risk 6. that number selects a point on the pareto frontier. no new physics, no new search.

cool waypoints and rest stops. this is the risky one so build it as a post pass on the already chosen route, not as a constrained search. walk the route, accumulate thermal load, and when it crosses a threshold look for a fountain or cooling center or park within a small detour budget and offer it as an insertion. if it's not working the night before, delete the post pass and nothing else in the system notices. that isolation is deliberate.


## the client

react plus maplibre plus deck.gl.

the shadow layer is deck.gl with sunlight, driven by sun position computed client side from the noaa solar position algorithm. this is independent of the server entirely, which is why the time scrubber feels instant.

the route layer draws the chosen route as a line colored by felt temperature along its length, so you can see the hot blocks. two routes on screen at once, fastest and shadeway, with the comparison card.

the ui pieces: time scrubber along the bottom. route compare card with both options and the delta. departure curve, the little heat versus time chart. heat profile selector. amenity pins for fountains and cooling centers.

one design note: the hero number is the degrees. make it big. everything else is supporting evidence.


## repo scaffold

shadeway/
  README.md
  Makefile                      make data, make warm, make serve, make dev
  pipeline/                     python, offline, never ships
    shadeway_pipeline/
      config.py                 bbox, crs, source urls, one city profile
      sources/                  one module per dataset, each idempotent
        cscl.py
        sidewalks.py
        buildings.py
        trees.py
        canopy.py
        landcover.py
        amenities.py
      graph/
        build.py                cscl to per side sidewalk edges
        crossings.py            synthesize intersection crossings
        sample.py               sample points every 10m along edges
      scene/
        buildings.py            footprints to prisms
        trees.py                census plus allometry to crowns with tau
        surfaces.py             landcover to albedo
      emit.py                   writes scene.parquet, graph.parquet
      validate.py               connectivity, coverage, sanity checks
    tests/
  server/                       fastapi, python
    shadeway/
      occluder.py               strtree, ray cast, the 2d test
      horizon.py                the lazy cache, svf derivation
      thermal/
        solar.py                sun position
        tmrt.py                 solweig lite
        utci.py                 polynomial plus the lookup table trick
        weather.py              open meteo client plus cache
      router/
        graph.py                load into numpy arrays
        cost.py                 the callback the router calls
        bicriteria.py           martins with epsilon dominance
        timedep.py              the fixed point iteration
      api.py                    routes, endpoints
      scene_edit.py             plant trees, invalidate cache
    tests/
  web/                          react, typescript
    src/
      map/
        ShadowLayer.tsx
        RouteLayer.tsx
        AmenityLayer.tsx
      ui/
        TimeScrubber.tsx
        RouteCompare.tsx
        DepartureCurve.tsx
        HeatProfile.tsx
      state/
      api/
  docs/
    model.md                    the physics, written up for judges to read

the reason model.md exists as its own doc: if a judge asks "is this real or did you make it up", you hand them a document with equations and citations. that's worth an enormous amount and costs an afternoon.


## build order and who does what

three tracks that can run in parallel once the interfaces are frozen.

day one, before anything else: freeze the shapes. graph.parquet schema, scene.parquet schema, and the route json response shape. write them down. stub them with fake data. now tracks b and c can work all day without waiting on track a.

track a, python person. sources, graph build, crossings, scene build with the tree allometry, validate. this is the longest pole so start it first and don't let it block anyone.

track b, python or backend person. occluderfield, horizon cache, thermal model, router. thermal model can be built and fully tested against published reference values with zero real data, so start there while track a is still downloading things.

track c, frontend person. map, shadow layer, scrubber, all the ui. mock the route json from hour one. the shadow layer is entirely client side so it can be finished and beautiful before the server does anything real.

merge point: when track a emits real files, track b points at them instead of stubs and track c points at a real server instead of mocks. if the interfaces were frozen properly this is a small day.


## risks, ranked, and what to do

cold cache on stage. mitigation is make warm, run it before you present, and also just have the demo corridor pre warmed. this is fully solved, just don't forget to do it.

crossing synthesis at intersections is fiddly. nyc intersections have weird geometry, plazas, one way pairs, bridges. mitigation: validate.py should report connectivity stats and flag disconnected components. if a neighborhood is broken you want to know on day two not on demo day. fallback if it's a disaster: use osm footways for the pedestrian network instead, nyc osm coverage is decent.

tree allometry producing nonsense crowns. mitigation is the canopy raster cross check. it's a two hour job and it catches this immediately.

thermal model constants being wrong. mitigation is golden value tests against published references, and writing model.md honestly. if a number is uncertain, say so in the doc. a judge respects "we used the published value and here's the citation" and also respects "this constant is approximate and here's why it doesn't move the answer much".

bicriteria search blowing up on long routes. mitigation is epsilon dominance, plus a hard cap on labels per node. if it still struggles, fall back to running the single objective search at a handful of lambda values, which gives you a coarse frontier and is basically free.

scope. four features plus a physics engine plus a data pipeline is a lot. see the cut list.


## what to cut, in order, if time gets tight

cut cool waypoints first. it's a post pass, deleting it touches nothing else. that isolation is why it was designed that way.

cut brooklyn second. manhattan below 96th is about a quarter of the edges and every demo you'd actually give happens there anyway.

cut the departure optimizer third, but only if you really have to, because it's the most novel thing in the project and it's cheap once the router works.

do not cut the felt temperature number. do not cut the shaded side of street guidance. those two are the entire differentiation.


## the demo, roughly

open on midtown at 3pm on a hot day. shadows are already on the map and already moving when you drag the scrubber. that's the first five seconds and it should land before you say a word.

type in a route. two lines appear. fastest is 18 minutes and feels like 41. shadeway is 23 minutes and feels like 33. say the sentence: five extra minutes buys you eight degrees.

zoom into one block. show the turn card: cross to the east side of 5th, the west side is in full sun until 6:40. this is the moment people check it against their own memory of the block and believe you.

pull up the heat profile. switch to high risk. the route changes. say who that's for.

show the departure curve. leave 38 minutes later, seven degrees cooler. nobody else does this.

close on the tree thing if you have time. plant trees on a corridor, re run, show the corridor got cooler. that's the "this is a planning tool too" beat.

