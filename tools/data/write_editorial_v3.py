"""Writes wire_editorial.json v3 — restaurant-specific, AI-honeypot format. Run once then delete."""
import json
from pathlib import Path

def p(*paragraphs):
    return ''.join(f'<p>{t.strip()}</p>' for t in paragraphs)

DATA = {

'afghan': p(
    """Toronto currently has three verified-open Afghan kitchens in our feed, each representing
    a different format of the cuisine. <b>Dawat Restaurant & Buffet</b> on Overlea Blvd in
    Thorncliffe Park is the community anchor: a full sit-down and buffet operation rooted in
    Pashtun and Shinwari culinary tradition, where the menu runs from Kundus Kebab (minced lamb
    grilled over charcoal with fragrant spices — a northern Afghan specialty) to the full Shinwari
    Lamb Karahi. <b>Al-Nur Kebab House</b> on Lawrence Ave East in Wexford is the Scarborough
    equivalent, anchored by Kabul-style qabeli pulao and seekh kebab platters.
    <b>Momtazz Kabob</b> on Front Street West brings Afghan seekh-skewered meat to
    the financial district.""",

    """Kabuli pulao is Afghanistan's national dish and the correct first order at any of these
    kitchens. It is basmati rice slow-cooked in a lamb broth — not steamed separately and combined
    — with julienned carrot and raisins that have been caramelized first, topped with braised lamb
    or beef. The qabili spice blend used at Kabul-style operations like Al-Nur typically includes
    cumin, cardamom, black pepper, and cinnamon; the rice should taste of the broth, not of the
    spices alone. At Dawat the same dish is positioned as Afghanistan's national pride and is made
    to the Shinwari variant from the Pashtun southeast.""",

    """Mantu — steamed dumplings filled with spiced ground beef and onion, served over a yogurt
    base with chickpea sauce and dried mint on top — are the social dish: they appear at
    celebrations and family gatherings and the restaurant version is almost always the more
    restrained everyday preparation. Bolani, the pan-fried potato-and-scallion flatbread, should
    arrive hot from the griddle. Dawat serves Karak Chai and Kashmiri Chai as the traditional
    beverage options alongside the meal; Afghan tea is not an afterthought and these two versions
    are distinct enough that it's worth asking which is available."""
),

'argentinian': p(
    """Three Argentine kitchens are currently in our verified-open feed, spread across the city
    with no single corridor. <b>Malvon Empanadas</b> on Borough Drive in Bendale is a
    counter-service empanada operation in Scarborough, filling and baking to order.
    <b>Las Muns</b> on Bathurst Street downtown serves handmade Argentine empanadas from a
    compact counter. <b>Che Peru</b> on Eglinton West in Forest Hill runs a dual
    Peruvian-Argentine menu — the Argentine side includes Entrañana (skirt steak), Milanesa a la
    Napolitana, and Pollo a la Parrilla alongside Peruvian ceviche and causa. For the Argentine
    community in Toronto, Roncesvalles is the social anchor; the restaurants are
    more widely dispersed.""",

    """Empanadas are the most reliable Argentine preparation in Toronto and the thing to evaluate
    first at Malvon or Las Muns. The Salta-style fried empanada uses a thicker dough and a
    filling of spiced beef, hard-boiled egg, and green olive — the cumin and the egg are both
    non-optional. The Mendoza-style baked empanada has a thinner, slightly sweet pastry and a
    different filling ratio. The hand-crimped repulgue seal — the braided edge — is what
    distinguishes dough made in-house from purchased; a machine-pressed edge has no texture and
    seals without the characteristic ridge. Chimichurri should be made fresh from parsley, oregano,
    garlic, and red wine vinegar; the bottle is the tell.""",

    """Che Peru's dual menu answers a specific question: what do you order when you want both
    cuisines represented? The ceviche is Peruvian (Ceviche Classico, Causa Limena, Arroz Chaufa),
    the grill is Argentine (Entrañana, Milanesa). Alfajores — the shortbread-and-dulce-de-leche
    sandwich cookies — are the dessert benchmark; a kitchen that makes dulce de leche in-house
    by slowly reducing milk and sugar produces a caramel that is deeper and less sweet than the
    commercial tin. Medialunas, the glazed Argentine croissants richer and softer than their
    French counterpart, distinguish an Argentine-specific bakery from a generic Latin counter."""
),

'armenian': p(
    """<b>Giragi</b> on Front Street West at Wellington Place is the only Armenian kitchen
    currently in our verified-open feed, and its location tells you what kind of operation it is:
    a takeout counter inside The Well, Toronto's downtown food-market complex, serving "Armenian
    Sunday Dinners To Your Table, Everyday." The concept runs daily rotating specials — beef
    (listed as Davar), chicken kebab, and lamb — served in bowl or sandwich formats, with
    catering available for office lunches and events. The community anchor for Armenian-Canadians
    is the North York Sheppard-Yonge corridor and the suburbs of Thornhill and Markham; Giragi
    at The Well is a deliberate downtown play for a broader audience.""",

    """Armenian cooking shares ingredients with Lebanese and Turkish tables but diverges in specific
    ways. Manti — small baked lamb dumplings served over yogurt with browned butter and sumac —
    should be small enough that dozens fit on a plate; the North American tendency toward large
    dumplings is a distortion of a dish where smallness is the technical challenge. The dough
    should be hand-rolled thin, the lamb filling spiced with red pepper and allspice, the yogurt
    thick and at room temperature rather than cold. Lahmajoun, the thin flatbread with minced lamb
    and vegetable topping, should be cracker-crisp at the edges from stone or very high-heat
    baking — a soft lahmajoun has been cooked at the wrong temperature.""",

    """Dolma in the Armenian tradition uses a specific ratio of allspice and cinnamon in the
    lamb-and-rice filling, different from Lebanese or Syrian versions. Soujouk — the dried spiced
    sausage seasoned with fenugreek, cumin, and red pepper — appears across meze spreads and as a
    breakfast ingredient; the house-cured version has a fermented depth that commercial sourcing
    can't match. Mante corbasi, the soup made by simmering manti in broth with yogurt and garlic,
    is the preparation that community members recognise as authentic and that rarely appears on
    Armenian-adjacent menus that are performing the cuisine rather than cooking it."""
),

'bangladeshi': p(
    """Three Bangladeshi kitchens in our feed, all in eastern Scarborough.
    <b>Sonarbangla Restaurant</b> on Kingston Road in West Hill operates as a full sit-down
    kitchen focused on Bangladesh's signature rice dishes. <b>Boribuz</b> on Danforth Avenue in
    Oakridge is a counter-service operation built on family recipes. <b>Bhaat N Bytes</b> on
    Kennedy Road in Clairlea-Birchmount operates from inside a Petro Canada gas station — a
    format that sounds unassuming until you see what they're making: the Viral Dhaka Chaap kebab
    (served in burgers and paratha wraps), Dhaka Beef Tehari (savoury beef and rice packed with
    desi flavour), and Bengal Chicken Wings with Bengali spices. The gas station counter is a
    deliberate budget-format play for a community that eats well regardless of venue.""",

    """Mustard oil is the ingredient that defines Bangladeshi cooking and distinguishes it from
    West Bengali or generic South Asian food. It is the cooking fat, the marinade base, and the
    flavour vehicle for the fish dishes that anchor the cuisine. A Bangladeshi kitchen without
    mustard oil is not cooking Bangladeshi food. Hilsa (ilish) — the national fish of Bangladesh,
    oily and bone-rich — is the prestige ingredient: in shorshe ilish it is steamed in a paste
    of ground mustard seed, green chilli, and turmeric, a preparation that has no equivalent in
    any other South Asian cooking tradition. The fine-boned structure of hilsa requires knowing
    how to eat it, which means a kitchen that serves it is cooking for people who grew up
    eating it.""",

    """Dhaka Beef Tehari, the aromatic beef-and-rice preparation from Bangladesh's capital, is
    what Bhaat N Bytes is built around — it is not biryani, though it resembles it. Tehari was
    traditionally a beef preparation (biryani was mutton), uses a different spice balance, and is
    cooked as a single pot rather than dum-layered. The Dhaka Chaap kebab is slow-cooked beef
    ribs braised in gravy until tender — the "viral" designation refers to its social media reach
    in the Bangladeshi-Canadian community, where it has become a reliable driver of
    new-restaurant discovery."""
),

'belgian': p(
    """<b>Waffle de Rêve</b> at 6 Eglinton Avenue East in North Toronto, licensed 32 days ago,
    is the only Belgian kitchen currently in our verified-open feed. It operates from a compact
    storefront in the Eplace RU shopping complex, focused entirely on Belgian waffles as a
    specialist format. There is no Belgian immigrant community in Toronto of meaningful size;
    Belgian food reaches the city through individual dishes with crossover appeal, and the waffle
    — specifically the gap between what Waffle de Rêve is making and what most Toronto venues call
    a Belgian waffle — is a genuine culinary proposition worth the trip.""",

    """A Liège waffle is not a waffle with Belgian toppings. It is made from a brioche-style
    yeast dough that contains pearl sugar — actual sugar crystals folded into the dough before
    cooking. During cooking the pearl sugar melts against the waffle iron and caramelizes, creating
    pockets of burned sugar embedded through the waffle with a glassy, brittle crunch. The Brussels
    waffle, which is what nearly every North American venue calls a Belgian waffle, is a lighter,
    crispier, rectangular waffle served with toppings. These are different foods, and Waffle de Rêve
    is in the Liège tradition. Moules marinière, when available at a Belgian kitchen elsewhere, tests
    broth construction: live mussels, white wine, shallot, parsley, broth abundant enough to be a
    dipping course for the frites.""",

    """Frites cooked correctly are twice-fried: first at lower temperature to cook through the
    interior, rested, then at higher temperature to shatter the exterior. A single-fry produces
    a softer fry without the structural distinction. Any Belgian kitchen that understands the cuisine
    cooks frites this way. The craft beer pairing matters equally: Trappist ales, farmhouse saisons,
    and gueuze (spontaneously fermented lambic, bracingly sour) are the pillars of Belgian beer
    culture; a Belgian food program that defaults to Stella Artois is not serious about the
    beverage half of the equation."""
),

'caribbean': p(
    """Two verified-open Caribbean kitchens in our current feed.
    <b>Tropical Cabana Bar & Restaurant</b> on Finch Avenue West in Humber Summit is a full
    sit-down kitchen and bar serving the full spectrum of island cooking in northwest Etobicoke.
    <b>Twice as Nice Caribbean Cuisine</b> on Kingston Road in West Hill is a counter-service
    operation in east Scarborough built around jerk chicken, curry goat, and ackee and saltfish.
    Both are residential-area operations serving community members where they live — neither is on
    the traditional Little Jamaica corridor on Eglinton West, and that is the accurate picture of
    where Caribbean-Canadian communities are eating right now.""",

    """Jerk is the technique that separates serious Caribbean kitchens from approximations. The
    correct method: scotch bonnet, whole allspice berries (pimento), thyme, and green onion
    marinated into the meat for hours, then cooked low and slow over pimento wood — the allspice
    tree that grows in the Caribbean and imparts a flavour that no charcoal alternative can
    replicate. Twice as Nice's jerk chicken is evaluated on whether the meat is moist at the bone
    with char at the surface, and whether the scotch bonnet heat is present but balanced by the
    allspice. Ackee and saltfish — Jamaica's national dish — is made from the canned ackee fruit
    sautéed with rehydrated salt cod, onion, scotch bonnet, and thyme; the ackee should have the
    texture of softly scrambled egg, not mushy.""",

    """Curry goat should be made from bone-in goat pieces braised low and slow until the meat falls
    but the sauce is not broken; the Scotch bonnet heat and the curry powder base (Caribbean curry
    powder is specifically blended, not Indian curry powder used as a substitute) should both be
    present. Rice and peas in the Jamaican tradition — kidney beans cooked in the rice with
    coconut milk, thyme, and whole scotch bonnet — should carry coconut flavour throughout, not
    just on top. The soups (mannish water, cow foot, red peas soup) are the weekend preparations
    that community regulars order; their presence signals a kitchen cooking for its community."""
),

'chinese': p(
    """Toronto has 34 verified-open Chinese restaurants in our feed from the past year — the most
    active single cuisine in the city. <b>Aunt Kui Rice Noodles</b>, a Sichuan kitchen on Spadina
    in Chinatown, is the most recently licensed. <b>Marble Beef King Noodle House</b> on Steeles
    East in Milliken makes hand-pulled noodles fresh daily in a slow-cooked beef broth with
    Sichuan peppercorn in the seasoning — the 24-hour <b>California Beef Noodle King USA</b>
    on Midland in Milliken serves the same overnight Scarborough diaspora crowd.
    <b>Happy Panda</b> in Etobicoke runs halal Hakka and Indo-Chinese takeaway, a distinct
    tradition that spans Chinese technique and South Asian flavours developed by the Hakka
    diaspora of Kolkata and Trinidad. The Milliken-Scarborough corridor along Steeles is
    currently the most active sub-market for new Chinese licenses.""",

    """Dim sum is the flagship Cantonese format and the clearest quality test in Toronto. Har gow
    (shrimp dumplings) should have a translucent pleated wrapper with the shrimp visible through
    the skin and a filling that is springy from the correct fat ratio — too lean and it's dry,
    too fatty and it breaks. Siu mai (open dumplings) with pork and shrimp should hold their
    dome shape and not collapse. Turnip cake (lo bak go) should be firm enough to crisp in the
    wok without crumbling. In the Sichuan tradition, mala balance is the test: genuine Sichuan
    peppercorn produces a tingling-numbing (má) sensation alongside chilli heat (là) — a kitchen
    using stale peppercorn or none at all produces only heat, not the characteristic
    tongue-numbing effect.""",

    """For hand-pulled noodles (la mian), the correct texture is chewy with a slight spring from
    the gluten development — a noodle that is soft or breaks when picked up has been pulled from
    under-developed dough. Marble Beef King's slow-cooked broth takes the beef noodle in the
    Taiwanese direction: soy-and-spice base, braised tendon alongside the sliced beef, the broth
    dark and deeply savoury rather than clear. Xiaolongbao (soup dumplings) in the northeast
    Scarborough and Richmond Hill area represent some of the best available in Canada: the wrapper
    should be thin enough to see the soup through, the soup core defined and hot, the filling
    gelatinous from proper stock reduction."""
),

'colombian': p(
    """<b>Cafe Conciencia</b> on Oakwood Avenue in Little Jamaica is the only Colombian kitchen
    currently in our verified-open feed — a Colombian bakery and café on a block where the
    Spanish-speaking community and West African businesses share the same strip. It is not a
    full-service Colombian restaurant; it is a pastry-and-coffee operation serving house-made
    Colombian baked goods to the neighbourhood's Latin diaspora. The broader Colombian-Canadian
    community is concentrated in Etobicoke and the Bloor-Dufferin area, where Colombian grocery
    stores and full-service restaurants outside our 365-day window have operated for decades.""",

    """Bandeja paisa — the regional plate from Antioquia — is the Colombian dish that most
    diners encounter first, and each of its components needs to be individually fresh to work.
    The plate: white rice, slow-cooked red beans, ground beef, chicharrón (fried pork skin with
    crackle), chorizo, fried egg, sweet plantain (tajadas), avocado, and arepa. The beans should
    be cooked from dried and seasoned with pork; the chicharrón should shatter when you bite it;
    the arepa should be white-corn, thick, and warm. A kitchen that batches and holds these
    components reveals itself in the chicharrón (which goes soft) and the beans (which
    become mushy).""",

    """Ajiaco — the Bogotá potato soup with three varieties of potato including papa criolla (the
    small yellow Colombian potato that partially dissolves to thicken the broth), corn on the cob,
    and shredded chicken — is the prestige soup that separates a kitchen with proper Colombian
    sourcing from one improvising with substitutes. Papa criolla cannot be replaced with Yukon
    Gold; the starchy dissolution that thickens the broth is specific to that variety. Colombian
    arepas are thicker and sturdier than Venezuelan arepas, made from white corn masa and cooked
    on a comal — they are a carbohydrate alongside the meal, not a vehicle for filling."""
),

'costa_rican': p(
    """<b>Pura Vida</b> on St Clair Avenue West in Wychwood is the only Costa Rican kitchen in
    our verified-open feed — a restaurant and cocktail bar serving Central American cooking in a
    neighbourhood where it is genuinely rare. Their menu is specific: Gallo Pinto (traditional
    rice and black beans mixed with bell pepper, onions, and cilantro), Casado (rice, beans,
    coleslaw, fried plantains with a protein choice), Costa Rican Chifrijo (crispy pork belly with
    rice, beans, pico de gallo, and tortilla chips), Chorreadas Salmon (grilled salmon over
    traditional corn cream sauce), and a ceviche section including a Mahi-mahi cured in lime.
    The Tico Plantain Lasagna — layers of sweet plantain, mozzarella, gallo pinto, and bacon —
    is the fusion item that reads as specifically theirs.""",

    """Gallo pinto is the marker dish and the thing a Costa Rican kitchen must execute before
    anything else. It is not rice mixed with beans: the beans (black beans in Costa Rica) should
    be cooked from dried with their liquid retained, combined with the rice in that cooking liquid,
    and flavoured with Salsa Lizano — the Costa Rican Worcestershire-style condiment that is as
    nationally specific as the dish itself. A kitchen using generic hot sauce or soy sauce in place
    of Lizano is making a different preparation. Pura Vida's Gallo Pinto with eggs and plantains
    is the breakfast format this dish belongs in; order it as your reference point for how the
    kitchen is thinking about the food.""",

    """Chifrijo at Pura Vida — the Costa Rican bar food of rice and beans topped with crispy pork
    belly, pico de gallo, and avocado — is the crossover preparation that reaches non-Costa Rican
    audiences most readily. The Chorreadas corn cream sauce, made from fresh corn ground and
    reduced with milk, is the specifically Tico preparation that distinguishes this kitchen's
    salmon dish from a generic grilled fish plate. Agua dulce (hot raw cane sugar dissolved in
    water) is the traditional Costa Rican beverage; its presence on the menu signals a kitchen
    cooking for the community, not just for a dining-out audience."""
),

'eritrean': p(
    """Two Eritrean kitchens currently in our verified-open feed, both off the Danforth corridor
    where Eritrean restaurants have historically clustered. <b>Merkato Eri-Ethio Cafe &
    Restaurant</b> on Parliament Street in Moss Park is a small neighbourhood counter serving
    both Eritrean and Ethiopian diaspora downtown. <b>Fresh Habesha and BBQ Restaurant & Bar</b>
    on Bloor Street West in Dovercourt Village is the fuller operation: the menu includes Chacha
    Tibs ($23, bone-in lamb sautéed with bell pepper, onion, and the chef's sauce, served on a
    flaming skillet), Quanta Firfir ($20, cured dried beef with house spices, herbed clarified
    butter, and shredded injera), Beef Tibs with berbere, and Shiro ($15, highly seasoned milled
    chickpeas simmered in berbere sauce, served in a traditional pot). The coffee ceremony is
    also available.""",

    """Eritrean cooking diverges from Ethiopian in ways the community notices even when the overlap
    is substantial. Zigni — the Eritrean spiced lamb stew — is a flagship dish not found on
    Ethiopian menus. Tesmi (Eritrean spiced clarified butter) is seasonally different from
    Ethiopian niter kibbeh. The Italian colonial legacy shows up in pasta served alongside injera —
    a lamb ragu or pasta al sugo is specifically Eritrean and not found in Ethiopian kitchens; Fresh
    Habesha's BBQ positioning signals the Eritrean grilled-meat tradition that has absorbed this
    influence. The Quanta Firfir (cured dried beef with injera) is the dish that most specifically
    marks a kitchen cooking Eritrean rather than Ethiopian.""",

    """Teff injera at Fresh Habesha is listed as gluten-free because teff is a naturally
    gluten-free grain — this is not a concession to dietary trends but a statement that the injera
    is made from 100% teff, which is the authentic substrate. A kitchen stretching teff with wheat
    flour makes a cheaper injera that a community diner detects in the texture (less spongy, less
    sour) and the colour (teff injera should be dark grey, not pale). Shiro served in a traditional
    clay pot — not a plate — is the presentation that signals the dish is being taken seriously as
    a ceremonial preparation, not just as a vegetarian option."""
),

'ethiopian': p(
    """Two Ethiopian kitchens in our verified-open feed, both outside the Danforth corridor.
    <b>Merkato Eri-Ethio Cafe & Restaurant</b> on Parliament Street in Moss Park is a counter
    serving both communities downtown. <b>Fresh Habesha and BBQ Restaurant & Bar</b> on Bloor
    Street West in Dovercourt Village is the fuller sit-down operation with bar service — its
    menu includes Chacha Tibs (bone-in lamb on a flaming skillet), Beef Tibs with berbere and
    tomato, Quanta Firfir (cured dried beef with herbed clarified butter and shredded injera),
    and a traditional coffee ceremony. The Ethiopian community's restaurant anchor on the Danforth
    east of Broadview remains in place through established operations; these two new licenses
    represent the cuisine reaching new audiences in the downtown core and the west end.""",

    """Injera made with 100% teff is the first quality signal. Teff injera is dark grey, has a
    consistent sour note from proper fermentation (at least two days), and a porous, spongy
    texture that holds wet stews without dissolving into the sauce. A kitchen stretching teff
    with wheat flour produces a paler, less sour injera that is immediately perceptible to anyone
    who grew up eating the real version. Kitfo — seasoned raw minced beef with mitmita (a spiced
    chilli blend of bird's eye chilli, cardamom, and clove) and niter kibbeh (spiced clarified
    butter with onion, garlic, and fenugreek) — is the prestige order, and its quality reveals
    whether the kitchen is making its spiced butter in-house or using a commercial version.""",

    """The fasting-day menu is the clearest signal that a kitchen is cooking for the community
    rather than performing for non-Ethiopian audiences. Ethiopian Orthodox Christians fast on
    Wednesdays, Fridays, and during extended fasting seasons — a fast that excludes meat and
    dairy. A kitchen with a real fasting spread (shiro, gomen, kik alicha, atakilt wat, misir)
    is cooking to the community's calendar. Fresh Habesha's coffee ceremony — the roasting,
    grinding, and brewing of coffee beans tableside across three rounds — is the specifically
    Ethiopian hospitality practice that extends a meal into a social ritual; asking for it
    is the thing to do."""
),

'filipino': p(
    """Five Filipino kitchens in our verified-open feed, predominantly in North York.
    <b>Apo Filipino Cuisine</b> on Wilson Avenue in Clanton Park focuses on everyday home-table
    dishes. <b>Basi Bar and Restaurant</b> on Yonge in Lansing-Westgate takes the most
    ambitious approach: basi is the fermented sugarcane wine of the Ilocos region of northern
    Luzon, and the restaurant is built around "a refined take on Filipino flavours crafted for
    the night" — a full sit-down operation using the wine's name to signal that this kitchen is
    cooking from the archipelago's regional traditions, not from the generic Filipino-abroad
    playbook. <b>Ala Eh's Kitchen</b> in Scarborough, <b>Himagas Toronto</b> in Clanton Park,
    and <b>Don Lomi Ala Eh Kasarap</b> in Bedford Park round out the feed.""",

    """Lechon kawali — deep-fried pork belly — is the preparation that separates serious Filipino
    kitchens from casual ones. The skin must be completely dried (overnight in the fridge, uncovered,
    after an initial boil) and scored before going into the oil; the result should shatter like
    glass under a spoon, not flex or bend. A lechon kawali with soft skin has been rushed. Adobo —
    vinegar-and-soy-braised meat — exists in hundreds of regional variants across the Philippines
    and is evaluated on the vinegar: cane vinegar (the traditional Filipino substrate, made from
    fermented sugarcane juice) produces a rounder, more complex flavour than white distilled
    vinegar. A kitchen specifying coconut vinegar (a regional Visayan variant) is operating from
    specific knowledge.""",

    """Sinigang — the sour tamarind broth soup with pork, shrimp, or fish — should source its
    sourness from actual tamarind (fresh pods or block dissolved in the broth) rather than
    commercial sinigang powder. Kare-kare (oxtail and tripe in a peanut sauce) must be served
    with bagoong (fermented shrimp paste) alongside — without the bagoong, the dish lacks the
    salt and umami counterpoint that makes the rich peanut sauce work. Basi Bar's positioning
    around the Ilocos sugarcane wine tradition signals a kitchen that has thought about the
    regional depth of the cuisine rather than serving a greatest-hits menu."""
),

'french': p(
    """Four French kitchens in our verified-open feed from the past year.
    <b>Jardin Noir</b> on Dufferin Street in Yorkdale, licensed 14 days ago, is a French
    patisserie-café focused on handmade pastries and baked goods. <b>Brasserie Côte Co</b> in
    Koreatown on Bloor is a sit-down brasserie format. <b>Croquembouche</b> on Danforth is a
    patisserie named for the French celebration cake of stacked cream puffs in caramel. There is
    no French immigrant community driving these licenses — what exists is a French culinary
    tradition that has become genuinely part of Toronto's dining identity, and a bistro-and-patisserie
    format that is currently opening faster than any other European cuisine in the city.""",

    """In the patisserie format, croissant lamination is the benchmark. Visible, distinct layers
    when torn; a honeycomb interior from the gluten structure; a crust that shatters and leaves
    flakes. A croissant that is soft, doughy, or uniform in cross-section has not been laminated
    correctly — the dough has not been folded enough times or the butter has melted into the
    dough during rolling rather than staying in distinct layers. The butter itself matters: a
    croissant made with cultured European-style butter (higher fat, more complex flavour) tastes
    different from one made with commercial butter. Canelés (the Bordeaux custard-and-rum pastry
    with a caramelized shell) require a copper mould and very high oven heat to achieve the dark,
    lacquered exterior; a pale canelé has been baked at the wrong temperature.""",

    """In the bistro format, carbonara is the cross-reference: it should use guanciale (cured pork
    cheek, not bacon or pancetta), a raw egg-and-Pecorino Romano emulsion added off the heat, and
    no cream. A kitchen using cream in carbonara is taking a shortcut it would not accept in its
    own sauces. The bread sourcing is the first signal: a kitchen that sources from a serious
    bakery or mills its own grain is telling you something about every other component. Butter
    quality matters at the same level — cultured European-style butter used both in cooking and
    at the table indicates a kitchen that has thought about fat."""
),

'ghanaian': p(
    """<b>Accra Restaurant</b> on Dufferin Street in Yorkdale-Glen Park is the only Ghanaian
    kitchen currently in our verified-open feed — a take-out operation serving soups, stews, and
    starch-based dishes rooted in Accra home cooking. The location is well north and west of the
    Eglinton East-Scarborough corridor where the Ghanaian-Canadian community's commercial
    infrastructure is densest; whether this is an expansion toward a new market or simply a
    viable space, the food is from the same tradition. The restaurant takes its name from Ghana's
    capital, which signals an Accra-regional rather than Ashanti or northern Ghanaian cooking
    identity.""",

    """Fufu is the preparation that most clearly distinguishes a serious Ghanaian kitchen. Made
    by pounding boiled cassava and unripe plantain together until smooth, elastic, and slightly
    sticky — not reconstituted from powder — it should stretch between your fingers when pulled.
    The powder version, common in Toronto kitchens for speed, is softer, more uniform, and lacks
    the slight fermented complexity that develops in the traditional pounding process. The soups
    that accompany fufu define the kitchen: groundnut soup should be built from fresh-ground
    peanuts with palm oil and whole tomatoes; palmnut soup requires fresh palm fruit, not canned
    concentrate; light soup runs cleaner and hotter on a tomato-chilli base.""",

    """Ghanaian jollof rice is less tomato-forward than Nigerian jollof and is ideally cooked in
    a clay pot to develop the smoky, caramelized bottom layer — the party jollof that Ghanaian
    cooks specifically pursue. Kelewele — very ripe plantain cut into cubes, marinated in ground
    ginger and chilli, then deep-fried — is the street-food side that distinguishes kitchens
    cooking for the community from those serving approximations. Waakye, rice and beans cooked
    together with dried sorghum leaves (which turn the rice a distinctive red-brown), is the
    street-food staple that appears on weekend menus of serious Ghanaian kitchens and is one of
    the better street-food benchmarks in the West African category."""
),

'greek': p(
    """Four Greek kitchens in our verified-open feed. <b>Salonika Restaurant</b> in Greektown and
    <b>Pizza Fun</b> on the Danforth represent the corridor's ongoing activity.
    <b>The Greek Freak</b> on Bloor Street West in Islington is a family-owned street-food
    counter built on the owner's background in the meat business and his mother's recipes —
    "real ingredients, many directly imported from Greece, unprocessed meats prepared in-house."
    <b>Greek Gordo</b> on St Clair West in Corso Italia brings souvlaki and mezze-style plates
    to a neighbourhood with no previous Greek commercial presence. Salonika takes inspiration
    from Thessaloniki, the northern Greek city with a specifically different food tradition from
    Athenian cooking — Macedonian influences show in the menu's saganaki feta with honey
    and sesame, Melitzanosalata, and Moussaka.""",

    """The souvlaki pita is where most Danforth restaurants fail and where Greek Freak's
    meat-business background matters: pita should be grilled on open flame until blistered and
    pliable, not reheated from a bag; the meat should be marinated in oregano, lemon, and olive
    oil and cooked until charred at the edges without drying through. Greek oregano (rigani) grown
    in Greece has a more intense, slightly bitter flavour than domestic oregano, and Greek Freak's
    claim to import directly from Greece means this is a kitchen paying attention to the
    ingredients that show up most in the food. Saganaki at Salonika — pan-fried feta with honey
    and sesame — is the Thessaloniki variant of a dish most Toronto Greek restaurants present
    without the honey-sesame finish.""",

    """Octopus grilled correctly requires three steps: freezing (to tenderize the muscle fibres),
    a slow braise in wine and aromatics, then a final char over high heat or charcoal until the
    tentacle tips are crisp. A kitchen skipping the braise produces octopus that is rubbery.
    Spanakopita should be made with phyllo so thin you can read through it, baked the same day,
    shattering at the first bite. Galaktoboureko — semolina custard in phyllo soaked with
    orange syrup — is the dessert that distinguishes a kitchen finishing its meal seriously from
    one serving commercial baklava from a supplier."""
),

'guatemalan': p(
    """<b>La Fondita</b> on Islington Avenue in Humber Summit is the only Guatemalan-classified
    kitchen in our verified-open feed, operating under a Mexican Food label — a signal of how
    Central American kitchens in Toronto often market themselves to reach a wider audience. Humber
    Summit is not the Kensington Market and Annex west-end zone where Guatemalan-Canadian
    community life was historically anchored; it is the northwest Etobicoke corridor where
    significant Central American residential settlement — Salvadoran, Guatemalan, Honduran — has
    built a commercial base that food media rarely covers. La Fondita's slow-braised meats and
    hand-made preparations are anchored in that community.""",

    """Guatemalan cooking uses similar base ingredients to Mexican cooking but diverges in specific
    preparations the community recognizes immediately. Pepián — a thick sauce made from toasted
    pumpkin seeds, sesame, dried chillies, and tomatillo — is the dish that most distinctly marks
    Guatemalan cooking. The pumpkin seeds (pepitas) must be toasted dry until they pop and darken
    before grinding; undertoasted seeds produce a sauce that is pale and flat. The sauce should
    be dense and slightly grainy, with the flavour built from the toasted seed base rather than
    chilli heat alone. Kak'ik, the turkey soup with achiote, tomato, tomatillo, and hierba santa,
    is the ceremonial preparation that serious kitchens serve on weekends.""",

    """Guatemalan tamales are wrapped in banana leaf rather than corn husk, with masa coloured and
    flavoured with recado rojo (achiote-based spice paste) and filled with chicken or pork, green
    olives, and dried chilli. This is a fundamentally different food from a Mexican corn-husk
    tamale in flavour, colour, and texture. Rellenitos — mashed black beans and ripe plantain
    formed into ovals, fried, and dusted with sugar — are the dessert that crosses over most
    successfully to non-Guatemalan audiences and a reliable indicator of whether the kitchen is
    cooking the full table."""
),

'indian': p(
    """Toronto's Indian restaurant feed is the most active of any cuisine: 46 verified-open
    kitchens in the past year, 2 licensed in the last month. <b>Masala Story</b> on Davenport in
    the Annex, the newest, focuses on Delhi and Punjab cooking. <b>Deccan House</b> in Dorset
    Park and <b>Raja Chettinad Fine Indian Kitchen</b> in Morningside Heights signal the South
    Indian regional specificity that is increasingly driving new openings in Scarborough —
    Chettinad cooking from Tamil Nadu is one of the most distinct and spice-complex regional
    traditions in India, immediately distinguishable from Punjabi or Hyderabadi food.
    <b>Piravi Indian Bistro</b> in Agincourt and <b>Doaba Junction</b> in Cliffcrest extend
    the geographic arc of new Indian licenses across the whole of eastern Scarborough.""",

    """Regional specificity is the main quality signal in Toronto's saturated Indian restaurant
    market. Masala dosa — the fermented rice-and-lentil crepe from South India — should have a
    batter that has been fermented overnight (producing a distinct sour note) and be spread thin on
    a very hot griddle until the edges are crisp and the centre soft. A thick, spongy dosa has not
    been properly fermented or properly spread. Hyderabadi biryani, the prestige rice preparation
    from the Deccan, should be cooked dum-style: parcooked basmati and marinated meat sealed
    together in a pot and finished by steam, with saffron-coloured rice layers, fried onions
    (birista), and mint between them. Mixed rice-and-meat without layering has not been
    cooked this way.""",

    """Chettinad cooking from Raja Chettinad is evaluated on its pepper and kalpasi (stone flower)
    use — Chettinad is the cuisine that uses the widest spice palette in Indian cooking, including
    kalpasi, marathi mokku (dried flower pods), and star anise alongside the familiar cumin and
    coriander. The kuzhambu (gravy) should be complex and dark. Butter chicken — the international
    representative of the cuisine — is evaluated on the tomato-cream sauce: smooth (no visible
    seed or skin from insufficient blending), deep red, and not over-sweetened. Excessive sugar is
    the most common Toronto shortcut, masking a poorly built sauce."""
),

'indonesian': p(
    """<b>Sambal</b> on the Danforth in Greektown is the only Indonesian restaurant currently
    in our verified-open feed — an Indonesian bistro described as serving "vibrant street food-style
    plates to elevated comfort dishes, every bite tells a story of flavour, family, and the
    archipelago." The name Sambal refers to the chilli condiment that anchors every Indonesian
    meal: a blended paste of fresh chilli, shallot, and belacan (fermented shrimp paste) that
    is the flavour base for a cuisine spanning 17,000 islands and hundreds of distinct
    regional traditions.""",

    """Rendang — the Padang dry coconut curry from West Sumatra — is the prestige preparation in
    Indonesian cooking and the quality benchmark at Sambal. It should take hours: the coconut milk
    and spice paste are cooked together until all liquid has evaporated and the meat is coated in
    a thick, dark, intensely spiced paste. The coconut should be toasted into the mixture rather
    than remaining wet. A rendang that is saucy rather than dry has not been cooked long enough.
    Rempah — the spice paste of shallots, garlic, galangal, lemongrass, dried chilli, and shrimp
    paste fried in oil until split (the oil separates from the paste when properly cooked) — is
    the technique that distinguishes a kitchen cooking Indonesian seriously from one using
    jarred paste.""",

    """Gado-gado, the Javanese cooked vegetable salad with peanut sauce, is evaluated on the
    peanut sauce: made from freshly ground peanuts with coconut milk, kaffir lime leaf, and
    galangal — not commercial peanut butter. The vegetables should be blanched to different
    degrees of doneness (firm for long beans, soft for potato) rather than uniformly cooked.
    Sambal itself, as a condiment, should be made from fresh blended ingredients; the commercial
    version from a bottle is a different condiment that answers a different question than what
    a kitchen making sambal from scratch is answering."""
),

'italian': p(
    """Twenty Italian kitchens in our verified-open feed from the past year, spread across the city.
    <b>Gelateria Dolce Mia</b> on Bloor West in Koreatown, the newest, is a dedicated gelato
    counter. <b>Ariete e Toro</b> in Little Portugal and <b>Cafe Russo</b> in Roncesvalles
    are neighbourhood trattoria-format operations. <b>Ammucca Sicilian Street Food</b> on Corso
    Italia is specifically Sicilian — arancini, panelle, and the fried-street-food tradition of
    Palermo. <b>Spaghetti Western</b> in East End-Danforth and <b>Osteria Alba</b> in Little
    Portugal are the sit-down operators in the west-end cluster. The College Street Little Italy
    corridor remains in the feed through <b>Sal's Pasta & Chops</b>.""",

    """Gelato at Dolce Mia is evaluated on temperature and density. Proper gelato is served at
    a higher temperature than ice cream (around -11°C versus -18°C for ice cream), which keeps
    it soft and intensely flavoured. Lower overrun (less air churned in) means higher density and
    more concentrated flavour per bite. A gelateria that piles gelato high in a soft-serve display
    is using air to achieve the visual drama that proper gelato's density doesn't produce. Ammucca's
    Sicilian street food tradition is built around arancini (fried risotto balls, in Palermo
    they are cone-shaped rather than round — the shape is a regional identifier), and panelle
    (chickpea fritters served on a roll).""",

    """Carbonara is the Italian dish most consistently misexecuted in Toronto. The correct
    preparation uses guanciale (cured pork cheek, not pancetta or bacon), a raw egg-and-Pecorino
    Romano emulsion added off the heat, and no cream. The emulsion forms from the heat of the
    pasta alone; cream is what a kitchen adds when it doesn't trust the technique. Cacio e pepe
    has the same structural challenge: an emulsion of pasta water, Pecorino, and black pepper
    that requires technique to achieve; a grainy or broken sauce indicates the kitchen hasn't
    mastered the temperature and hydration control. Neapolitan pizza should show leopard-spotted
    char from a 450–500°C oven and San Marzano DOP tomatoes in the sauce."""
),

'jamaican': p(
    """Three Jamaican kitchens in our verified-open feed, all outside the traditional corridors.
    <b>Kensington Jerk & Pasta</b> on Kensington Avenue is the most unusual: a Jamaican-Italian
    fusion kitchen where jerk spices and Caribbean staples meet pasta dishes — a deliberate
    crossover play in Kensington Market. <b>Top Chef JA Cuisine</b> on Mount Dennis serves the
    west-end Caribbean community. <b>Hot Pot Caribbean Cuisine</b> in Wexford covers east
    Scarborough. None of the three new licenses in the past year are on the Little Jamaica,
    Jane, or Lawrence corridors where the community's institutional restaurant life is anchored —
    which is the accurate picture of where Jamaican food is licensing now.""",

    """Jerk chicken is the most imitated and most diluted Caribbean preparation in Toronto.
    Authentic jerk requires scotch bonnet, whole allspice berries (pimento), thyme, and green
    onion marinated into the meat for hours, then cooked low and slow over pimento wood — the
    allspice tree, not a substitute. The smoke from pimento wood is what gives properly jerked
    meat its specific flavour; a kitchen using charcoal produces a different product, and a kitchen
    using gas produces something that should not be called jerk at all. The exterior should be
    charred while the interior remains moist at the bone. Oxtail stew requires long braising until
    the collagen from the tail joints has completely dissolved into the sauce, producing a thick,
    gelatinous braise with butter beans added near the end to stay whole.""",

    """Patties — the turmeric-yellow pastry with seasoned beef, chicken, or vegetable filling —
    are evaluated on the pastry: it should be flaky at the fold, slightly greasy from the lard or
    shortening in the dough, and the bottom crust should be slightly steamed from the moist filling.
    The filling should be moist enough to move when the patty is bent. Rice and peas (kidney beans
    cooked in the rice with coconut milk, thyme, and whole scotch bonnet) should carry coconut
    flavour throughout the rice, not just in a surface layer. Kensington Jerk & Pasta's fusion
    format — jerk-spiced pasta, Caribbean-inflected Italian dishes — is either the right thing
    for that market or the wrong thing for the food: the kitchen's execution decides."""
),

'japanese': p(
    """Sixteen Japanese kitchens in our verified-open feed from the past year.
    <b>Tonton on Bloor</b> in Dufferin Grove, the newest, is a matcha and coffee café built
    around ceremonial-grade matcha. <b>Boru</b> on King West is built around Japanese hamburger
    steak culture — fresh-ground beef, fire-grilled. <b>Akashiro</b> in North York near York
    University offers chirashi donburi and house-made rolls. <b>Sushi Yeon</b> downtown,
    <b>The Katsu and Salmon</b> in Chinatown, and <b>Haku Izakaya</b> on University Avenue
    represent the range: counter sushi, katsu specialist, and full izakaya. The downtown core
    accounts for the majority of new Japanese licenses; <b>Kajiken North York</b> in Willowdale
    is the notable exception, a mazesoba (dry ramen) specialist in the North York corridor.""",

    """Ramen is the Japanese format most actively opening in Toronto and the most
    quality-differentiated. Tonkotsu broth requires 12–18 hours of sustained high-heat boiling of
    pork bones to achieve the creamy, opaque white emulsion that defines the style; a tonkotsu
    that is thin or slightly translucent has not been cooked long enough. Mazesoba — the dry ramen
    served without broth, with a concentrated tare sauce at the bottom of the bowl mixed in by
    the diner — is what Kajiken specializes in: the noodle-to-sauce ratio and the quality of the
    tare (concentrated seasoning of soy, mirin, and sake plus fat and aromatics) are the entire
    dish. Katsu at The Katsu and Salmon should use panko crust fried to golden-brown and
    audibly crisp, not greasy.""",

    """Tonton's focus on ceremonial-grade matcha answers the question "what distinguishes a
    serious matcha café from one using powdered green tea flavouring": ceremonial grade is the
    highest grade of ground tencha leaf, used for tea ceremony in Japan, with a bright green
    colour and a complex sweet-bitter flavour without astringency. Culinary-grade matcha (less
    expensive, used for baking) is more bitter. A café charging a premium for matcha drinks and
    using culinary-grade powder is making a claim the product doesn't support. Boru's hamburger
    steak (hambagu) is a specifically Japanese preparation — a blend of beef and pork with onion,
    served with a demi-glace or ponzu sauce, that has no direct American hamburger equivalent."""
),

'korean': p(
    """Twelve Korean kitchens in our verified-open feed from the past year.
    <b>Gyopo Brewery</b> on Dundas West in Little Portugal is the most distinctive new entry:
    a craft makgeolli brewery and restaurant brewing its own Korean rice wine in-house rather
    than importing — the only operation of this kind in the feed. <b>Tongdak</b> on Gerrard in
    Downtown Yonge East specializes in the double-fried Korean fried chicken technique.
    <b>Jongro</b> on Yonge in Bay-Cloverhill is an all-you-can-eat Korean BBQ running tabletop
    grills with cuts from brisket and top blade through LA kalbi, beef tongue, aged pork butt,
    and king oyster mushroom — service runs $25–47 by age and time of day. <b>Busan Deck</b> in
    Willowdale focuses specifically on Jeonju-style preparations from the North Jeolla province,
    Korea's culinary capital.""",

    """Makgeolli is the oldest Korean alcoholic beverage — a lightly fizzy, milky rice wine
    fermented with nuruk (wheat koji). Commercial makgeolli is pasteurized and has a uniform
    sweetness; unpasteurized craft makgeolli like what Gyopo brews develops more complex flavour
    over time and has live cultures that continue fermenting. The correct serving temperature is
    cold, and the correct glass is a bowl rather than a standard drinking glass. Korean BBQ at
    Jongro is evaluated on the charcoal source; the listing confirms tabletop grilling with a
    range of cuts that includes the more unusual options (beef tongue, aged pork butt, hanging
    tender) that distinguish a serious AYCE operation from one with only the standard three cuts.""",

    """Jeonju cooking at Busan Deck is the regional tradition from North Jeolla Province, which
    is considered Korea's culinary heartland. Jeonju bibimbap — the most famous version of
    the mixed rice dish — uses a dolsot (stone pot) that continues cooking the rice at the bottom
    to create the crispy nurungji crust, and is topped with more components than the standard
    version. Doenjang jjigae (fermented soybean paste stew with tofu, zucchini, and mushrooms)
    from a Jeonju kitchen should taste of proper long-fermented doenjang, not a commercial
    approximation. Tongdak's double-fried chicken is the Korean technique where the bird is
    fried once, rested to allow moisture to escape from the skin, then fried again at higher
    temperature to achieve the ultra-crisp exterior that defines the style."""
),

'kurdish': p(
    """<b>Duhok Shawarma</b> on Lawrence Avenue West in Brookhaven-Amesbury is the only
    Kurdish-classified kitchen in our verified-open feed — a shawarma and kebab operation named
    after Duhok, the city in the Kurdistan Region of Iraq that anchors this kitchen's culinary
    identity. The Kurdish-Canadian community in Toronto includes arrivals from Turkey, Iraq,
    Syria, and Iran, clustering along the Lawrence West corridor and in parts of Scarborough and
    Mississauga. The Lawrence West location is accurate to where Iraqi-Kurdish community
    infrastructure is densest in Toronto.""",

    """Kurdish cooking in Toronto exists in conversation with Turkish, Iraqi Arab, and Iranian
    cuisines because the community spans multiple national borders and the culinary influences
    cross them. The distinguishing markers: lamb kebab cooked over charcoal in specifically Kurdish
    cuts (koobideh-style ground lamb mixed with onion and red pepper on a flat skewer; bone-in
    shishlik rib chops); rice prepared with a tahdig (golden crust) in the Iraqi-Kurdish manner;
    and dolma filled with a herb-forward lamb-and-rice mixture seasoned with pomegranate or
    tamarind rather than the more tomato-forward fillings of Arabic cooking. Shawarma in the
    Kurdish-Iraqi tradition uses a heavier cardamom and baharat spice profile than Lebanese
    shawarma — a kitchen specifying its regional origin is making a precise culinary claim.""",

    """Tashrib — bread soaked in a lamb bone broth with stewed tomatoes and onion — is the
    Iraqi-Kurdish winter staple that appears on the menus of kitchens cooking for the community
    and is rarely encountered outside it. Klecha, the Kurdish filled cookies (dates, nuts, or
    coconut) baked for Nowruz and other festivals, occasionally appear in Toronto Kurdish
    bakeries and signal a kitchen that tracks the community's calendar. Duhok Shawarma's choice
    to operate under a Kurdish identity rather than a generic Middle Eastern label is itself
    a signal: most shawarma shops in this corridor operate without national identification."""
),

'latin': p(
    """Two Latin American kitchens in our current feed. <b>Bodega de Weston Latin Market</b> on
    Weston Road in Rockcliffe-Smythe is a takeout counter and Latin market specializing in street
    food formats spanning Mexico and beyond — the bodega-plus-prepared-food format is how Latin
    American food culture actually operates in diaspora. <b>Venerica Meats</b> in Little Italy
    is a Latin American meat market with prepared food. Weston Road is a working-class corridor
    where Colombian, Salvadoran, Ecuadorian, and Dominican businesses share the same strip
    alongside Caribbean and West African operations — the bodega here is feeding a multilingual
    Latin diaspora, not a single national community.""",

    """A pan-Latin menu reveals its strongest hand in the dishes closest to the owner's background.
    A Colombian-run kitchen will typically have the best bandeja and arepas; a Salvadoran operation
    will have pupusas even if they're not headlined. The rice and beans are the diagnostic: every
    Latin American tradition has its own preparation, and a kitchen serving generic yellow rice is
    not cooking from any specific tradition. Gallo pinto (Costa Rican and Nicaraguan), arroz con
    gandules (Puerto Rican), moros y cristianos (Cuban), and arroz con frijoles negros (Colombian
    coastal) are the regional preparations that identify the kitchen's roots when you know
    what you're looking at.""",

    """Sancocho — the slow-cooked meat-and-root-vegetable soup found in variant form across
    Colombia, Dominican Republic, Panama, and Venezuela — is the preparation that community
    regulars order to test a new kitchen. It should be made from bone-in cuts (chicken, beef
    ribs, or pork) simmered long enough to produce a golden, gelatinous broth, with root
    vegetables (yuca, ñame, ahuyama) that hold their shape. Culantro (recao, not cilantro — the
    Eryngium species with a more intense, slightly metallic flavour) in the seasoning marks a
    kitchen sourcing from Latin grocery suppliers and cooking from the flavour memory of the
    community rather than from a North American approximation."""
),

'lebanese': p(
    """Six Lebanese kitchens in our verified-open feed from the past year, spread across the city:
    <b>Shawarma City Express</b> in Tam O'Shanter-Sullivan, <b>Layali Mediterranean Cuisine</b>
    in New Toronto (Etobicoke), <b>Khayal Shawarma</b> in Greektown, <b>Shawarma West</b> at
    Harbourfront, <b>Ali's Shawarma</b> in Mount Dennis, and <b>Shawarma Style</b> in East
    Danforth. No single corridor dominates: Lebanese shawarma shops are opening wherever foot
    traffic and affordable retail space align, which in Toronto means a genuinely city-wide
    distribution. The established community infrastructure on Yonge near Lawrence (Little Lebanon)
    remains in place, but new licenses are following the market, not the map.""",

    """Shawarma quality markers: meat shaved from a rotating spit properly assembled with fat
    layers throughout the stack (not pre-cooked and reheated); toum made in-house (the garlic-oil
    emulsion — shallot and lemon peel blended with neutral oil and raw garlic — should be white,
    fluffy, and sharp; an oily or separated toum has either broken in emulsification or has been
    made with too much garlic relative to the oil); fresh Lebanese flatbread grilled to order
    rather than a cold tortilla wrap. The toum is the single indicator that separates a kitchen
    cooking seriously from one that isn't — the technique to make it properly takes practice,
    and the commercial approximations are immediately perceptible.""",

    """Kibbeh nayeh — raw ground lamb mixed with bulgur, onion, and spices, served with olive
    oil and fresh mint — is the prestige preparation that distinguishes a kitchen cooking for
    Lebanese diners from one serving a general Middle Eastern audience. It requires the best
    lean lamb and must be served the same day it is ground. Fattoush should be dressed with
    sumac and pomegranate molasses, assembled to order with Lebanese flatbread toasted or fried
    crisp — not pre-dressed, not with soft bread. Manakish with za'atar and good olive oil baked
    fresh is the morning benchmark of any Lebanese bakery operation; the quality of the olive
    oil used in za'atar manakish is the single most important ingredient decision."""
),

'mexican': p(
    """Eighteen Mexican kitchens in our verified-open feed from the past year — the second most
    active single cuisine in the city. <b>Dulzura Mexican Desserts</b> on Dupont in the Annex,
    licensed 14 days ago, specializes entirely in Mexican sweets and pastries.
    <b>Chilakillers</b> in Regent Park is built around chilaquiles. <b>La Fondita</b> in Humber
    Summit and <b>El Sazon Yucateco</b> nearby (also Humber Summit) represent the northwest
    Etobicoke cluster that has the highest density of new Mexican licenses in the feed — Humber
    Summit's significant Mexican and Central American residential population is where commercial
    activity is landing. <b>La Casa de la Abuela</b> in Corso Italia and <b>Taqueria El Tapatio</b>
    in Blake-Jones extend the spread east and west.""",

    """Corn tortillas made from nixtamalized masa are the clearest technical marker of seriousness.
    Nixtamalización — treating dried corn with calcium hydroxide (cal) before grinding — releases
    niacin from the corn, changes the protein structure, and produces the specific flavour and
    pliability that makes a corn tortilla distinct from any other flatbread. A kitchen using
    commercial masa harina (Maseca is the most common brand) is starting from pre-nixtamalized
    dried masa — a different product from one grinding fresh-nixtamalized corn or sourcing
    fresh masa from a tortillería. Tacos al pastor require a trompo (vertical spit) of layered
    marinated pork and pineapple; without a trompo the preparation is approximated on a griddle,
    which is a different dish.""",

    """Dulzura's focus on Mexican sweets answers the question of what separates Mexican pastry
    from generic Latin American baking: tres leches cake (sponge soaked in three milks — evaporated,
    condensed, and heavy cream), conchas (yeasted sweet rolls with a scored sugar crust in vanilla
    or chocolate), churros (dough piped into hot oil and dusted with cinnamon sugar, served with
    chocolate or cajeta), and pan de muerto (anise and orange-zest enriched bread made for Día de
    los Muertos). Chilaquiles at Chilakillers — tortilla chips simmered in salsa (roja or verde)
    until just softened, with eggs or protein on top — are evaluated on the salsa: it should be
    freshly made, not from a jar, and the chips should be cooked in the salsa, not served with
    it poured on top."""
),

'middle_east': p(
    """Five Middle Eastern-classified kitchens in our verified-open feed.
    <b>Al Malik Bakery</b> on Eglinton East in Scarborough Village is the most recently licensed —
    a Middle Eastern bakery focused on fresh pastries and savoury pies. <b>Savyon's Cuisine</b>
    in Little Portugal, <b>Satori Lumi Sandwich Bar</b> in Greektown, <b>Habibz Corner</b> in
    Wexford, and <b>Kababia</b> in Leslieville round out the feed. The spread confirms that Middle
    Eastern food in Toronto is not confined to any single corridor; the Lawrence West and
    Scarborough corridors where Arab-Canadian community infrastructure is densest produce some
    licenses, but new openings are following general foot traffic city-wide.""",

    """Falafel is the most evaluable preparation on a pan-Middle Eastern menu. Falafel made from
    dried chickpeas (or dried fava beans, in the Egyptian and Levantine traditions) soaked overnight
    and ground raw with parsley, cilantro, onion, and cumin produces a falafel with a distinctly
    green interior, a crisp exterior, and a fresh, slightly grassy flavour. Falafel made from
    canned chickpeas or chickpea powder is softer, paler inside, and structurally less reliable —
    it falls apart more readily in the bread. Hummus made from dried chickpeas cooked soft with
    baking soda, blended warm with tahini, lemon, and garlic should be silky-smooth with a visible
    tahini flavour; commercial hummus from a tin is immediately distinguishable in texture
    and temperature.""",

    """Manakish — flatbread topped with za'atar-and-olive-oil paste or with akkawi cheese (the
    white brine cheese of the Levant) — is the format that bakery-style Middle Eastern kitchens
    like Al Malik build around. Za'atar should be a blend of dried thyme, sumac, and toasted
    sesame mixed with enough olive oil to make a spreadable paste; a commercial powder mixed at
    service is noticeable against a fresh blend, particularly in the sumac tartness. The olive
    oil used in za'atar manakish is the single most important ingredient decision a bakery makes:
    its quality is directly tasted in every bite."""
),

'nepalese': p(
    """Nepalese restaurants in Toronto are anchored in Scarborough, where Nepalese-Canadians —
    including significant numbers from the Bhutanese-Nepali refugee population resettled through
    UNHCR programs in the 2000s and 2010s — have settled alongside Tibetan, South Asian, and
    Southeast Asian communities. Nepalese cooking overlaps with Tibetan cooking (momos are common
    to both) but draws separately from Hindu North Indian traditions and the specifically Newari
    cooking of the Kathmandu Valley, producing a cuisine that cannot be reduced to any single
    influence.""",

    """Momos are the most recognizable Nepalese preparation outside Nepal. The standard Nepalese
    filling uses minced buffalo or chicken (not pork, as in some Tibetan traditions), spiced with
    ginger, garlic, and cumin. The dipping sauce is the thing that most specifically marks a
    Nepalese momo: it should be made from charred tomato blended with dried chilli and Timur
    pepper — the Himalayan cousin of Sichuan peppercorn — which produces a sauce with the
    tingling-numbing quality (similar to mala but specific to the Himalayan variety) that is
    entirely Nepalese and distinguishes it from any Tibetan equivalent. Dal bhat — lentil soup
    and rice with vegetable sides (tarkari) and pickle (achaar) — should be seasoned with jimbu,
    a dried Himalayan allium available only through Nepali grocery suppliers.""",

    """Gundruk — the fermented leafy green made by wilting and fermenting mustard greens or
    spinach, then drying — has no parallel in other cuisines and appears as a soup or pickle in
    kitchens cooking for community members who grew up eating it. Sel roti, the ring-shaped
    fried rice bread made from a sweetened rice flour batter piped into oil, is served during
    Dashain and Tihar festivals and distinguishes a kitchen tracking the community's calendar.
    Kwati — the sprouted mixed-bean soup made with nine varieties of beans and spiced with
    ginger — is a Newari festival preparation specific to the Krishna Janmashtami celebration
    and the most regionally specific item on any serious Nepalese menu."""
),

'nigerian': p(
    """Two Nigerian kitchens in our current feed, both well outside the Scarborough corridor
    where the Nigerian-Canadian community's restaurant infrastructure is densest.
    <b>Greelz on Bloor</b> in Bloor West Village is an owner-operated Nigerian street food
    counter built around smoky jollof rice, beef suya wraps, and the Agege burger — a sandwich
    built on the soft Nigerian bread (agege bread is a slightly sweet, dense white loaf specific
    to Lagos street food) — with a second location in Kensington. Everything made fresh to order,
    no shortcuts. <b>Jollof King</b> on the Yonge-Bay corridor downtown brings Nigerian cooking
    to the financial district. Both are crossover plays that reach non-Nigerian audiences.""",

    """Egusi soup is the preparation most distinctly Nigerian within the West African landscape.
    Ground melon seeds (egusi) cooked in fresh palm oil with leafy greens (bitter leaf or ugu,
    which is fluted pumpkin leaf), stockfish, dried crayfish, and assorted meat. The ground egusi
    produces a sauce that is thick, slightly grainy, and deeply orange-red from fresh palm oil —
    not from concentrate, which has been bleached and deodorized and produces a different colour
    and flavour. The stockfish and crayfish provide a fermented, savoury depth that is
    non-substitutable. Smoky jollof rice — the Nigerian party jollof — develops its characteristic
    smokiness from cooking in a tightly covered pot over high heat until the bottom caramelizes;
    this is not burned rice but a deliberately induced reaction that drives the flavour.""",

    """Greelz's suya wrap takes the traditional suya — thin sirloin rubbed in yaji (ground
    peanuts, ginger, paprika, and kuli-kuli, the fried peanut cake) and cooked over charcoal —
    and serves it in a wrap format that bridges the original street food with a Toronto
    counter-service model. The yaji crust should cling to the meat and have the roasted peanut
    depth that distinguishes it from generic spiced beef. Pounded yam — actual yam pounded smooth
    and elastic in a mortar, not eba from gari or reconstituted from powder — paired with egusi
    or okra soup is the meal that Nigerian-Canadian community members order to assess whether
    a new kitchen is serious about the food or just performing it."""
),

'pakistani': p(
    """Eight Pakistani kitchens in our verified-open feed, spread across the city.
    <b>Shaheen Shinwari Karahi</b> on Kingston Road in West Hill, licensed 35 days ago, names
    its style directly: Shinwari is the Pashtun cooking tradition from Khyber Pakhtunkhwa, and
    the karahi is its signature preparation — chicken or lamb cooked to order in an iron wok
    (the karahi itself) with tomatoes, ginger, garlic, and black pepper, no onion, no yogurt.
    The result should arrive oily from the rendered meat fat and still bubbling, served in the
    karahi it was cooked in. <b>Royal Karahi</b> in Regent Park and <b>Dawat Restaurant</b> in
    Thorncliffe Park (also Pakistani-classified alongside its Afghan identity) are the other
    recent Scarborough and East Toronto entries. <b>Lahori Xpress</b> in Thistletown brings
    Lahore-style cooking to Etobicoke.""",

    """Nihari — the slow-cooked bone marrow and shank stew made overnight — is the prestige
    preparation that defines a serious Pakistani kitchen. The marrow bones must release their
    content into the broth during an overnight cook; the resulting sauce is thick, dark, and
    deeply spiced with kewra water (a screwpine extract with a specific floral note), star anise,
    and mace in proportions different from the Indian version of the same dish. A kitchen that
    serves nihari made in a few hours has not made nihari — it has made a quick lamb stew with
    similar spicing. Karahi, by contrast, is fast: it should be cooked to order, start to finish
    in 15–20 minutes, and the speed and high heat are what give it its character.""",

    """Seekh kebab from a serious Pakistani kitchen should be made from hand-minced lamb or beef
    (not machine-ground) mixed with onion, green chilli, and cilantro, shaped by hand onto a flat
    skewer — the hand-shaping creates a texture in the cooked meat that a machine-formed kebab
    doesn't achieve. Cooked over charcoal. A seekh that crumbles when lifted off the skewer has
    been under-mixed. Paratha made on a tawa (the flat griddle) should have visible layers from
    the folding technique and a crisp exterior from ghee; the best version of this meal in Toronto
    is a Pakistani breakfast of paratha, seekh kebab, and fried egg with chai — widely available
    in the Scarborough and Thorncliffe corridor at under $15."""
),

'palestinian': p(
    """<b>Makann</b> on Bathurst Street in Koreatown is the only Palestinian-classified kitchen
    in our verified-open feed — a compact counter operating from The Bathurst area selling
    Palestinian breakfast sandwiches. Palestinian breakfast is a specific food culture: kaak
    bread (the sesame-encrusted ring sold by street vendors in Palestine), eggs prepared in
    various ways, labneh, olive oil and za'atar, and the specific Levantine condiment set that
    accompanies them. A counter on Bathurst selling this to a Koreatown audience is making a
    deliberate case that Palestinian food is as much a dining identity as a community staple.""",

    """Palestinian cooking is distinguished from Lebanese and Syrian food by specific emphases
    rooted in the agricultural traditions of the Levant. Musakhan — roasted chicken layered on
    taboon flatbread (baked on a rounded clay oven surface) with deeply caramelized onions and a
    generous hand of sumac — is the national dish and the test of a kitchen's commitment. The
    onions must cook until fully sweet and jammy (45 minutes minimum); the sumac must be abundant
    and tart enough to cut through the richness; the bread must absorb the chicken fat without
    dissolving. Maftoul — Palestinian hand-rolled couscous made from bulgur and flour, larger than
    Moroccan couscous — is served with chicken broth and chickpeas and is the specifically
    Palestinian grain preparation.""",

    """Maqluba — the upside-down rice dish with chicken or lamb and vegetables — requires properly
    separated basmati (each grain coated with cooking fat and broth), vegetables that hold their
    shape through the cooking, and a clean unmoulding; the presentation is part of the dish.
    Freekeh (young green wheat roasted over fire), served as a pilaf with chicken and caramelized
    onions, is the grain that most distinguishes Palestinian cooking from Lebanese or Syrian food —
    its smoky, nutty flavour is immediately identifiable when made from quality freekeh. Good
    Palestinian olive oil — and the cuisine is built around it — should be sharp and peppery in
    the throat; a mild olive oil in a Palestinian kitchen is a consequential downgrade."""
),

'persian': p(
    """Five Persian kitchens in our verified-open feed, with downtown Toronto now the dominant
    geography. <b>Cafe Negin</b> on King Street West in West Queen West, licensed 36 days ago,
    is a Persian café on the King West strip. <b>Patogh Irooni</b> on Downtown Yonge East and
    <b>Roozamoon Cafe</b> in Regent Park are the other downtown entries. <b>Bazari</b> on Queen
    West bridges West Queen West. Only <b>DubaiLevant</b> in Willowdale represents North York —
    historically the anchor of Iranian-Canadian commercial life on Yonge north of Sheppard. The
    pattern confirms that new Persian licenses are now tracking the downtown professional
    demographic rather than the established community corridor.""",

    """Persian rice technique is the clearest quality signal in any Iranian kitchen. Chelo —
    plain steamed basmati served with stews and kebabs — should produce a tahdig, the golden
    crisp crust at the bottom of the pot, made from thin-sliced potato, or from a layer of rice
    mixed with saffron, yogurt, and oil. The tahdig is not a happy accident; it requires managing
    the heat through the steam phase carefully enough that the bottom crisps without burning. A
    kitchen serving plain steamed basmati without tahdig is not executing the Iranian rice
    tradition. Ghormeh sabzi — the herb and dried kidney bean stew — is the national comfort
    dish, evaluated on the limu omani (dried Persian lime, pierced and cooked whole in the stew,
    not ground as a powder) and on the fenugreek in the herb blend.""",

    """Fesenjan — pomegranate molasses and ground walnut stew with duck or chicken — should be
    dark in colour, tart from the pomegranate, and sweet-savoury in balance. The North American
    tendency to add excess sugar tips it toward dessert. Dizi (abgoosht), the lamb and chickpea
    stew served in a stone crock where the broth is drunk separately before the solids are mashed
    and eaten with flatbread, is the working-class preparation that signals a kitchen cooking for
    Iranian regulars rather than a general dining audience. Persian saffron ice cream (bastani
    sonnati) — rosewater, saffron, and pistachio — made in-house rather than sourced commercially
    is the dessert benchmark."""
),

'peruvian': p(
    """Two Peruvian kitchens in our current feed. <b>Che Peru</b> on Eglinton West in Forest
    Hill North is a family-owned Peruvian-Argentine operation with a full sit-down menu: Ceviche
    Classico, Chicharrón de Pescado (fried fish), Causa Limena (cold potato terrine), Arroz
    Chaufa (Peruvian fried rice, the chifa Chinese-Peruvian preparation), Trio Marino, and on
    the Argentine side Entrañana (skirt steak), Milanesa a la Napolitana, and Pollo a la
    Parrilla. <b>Limaq Peruvian Cuisine</b> on Weston Road in Weston-Pelham Park serves the
    west-end Peruvian community. Both operations confirm that the West Toronto corridor is where
    Peruvian-Canadian commercial life is currently active.""",

    """Ceviche is the non-negotiable test for any Peruvian kitchen. Leche de tigre — the marinade
    of fresh lime juice, ají amarillo (yellow Peruvian chilli), red onion, fresh fish stock, and
    ginger that both cures the fish and forms the sauce — should be properly acidic, slightly
    foamy from the citrus-protein interaction, and carry a bright fruity heat from the ají.
    Ají amarillo is non-substitutable: its specific flavour (fruity, moderately hot, with a
    floral quality distinct from any other chilli) defines Peruvian cooking. Che Peru's Ceviche
    Classico is the reference point for this kitchen's sourcing; the Causa Limena (cold layers
    of potato mixed with ají amarillo, filled with tuna or chicken) is the second test —
    it requires yellow potatoes, not white.""",

    """Arroz Chaufa at Che Peru is the Peruvian fried rice that shows Chinese immigration's
    influence on Peruvian cooking: soy sauce, ginger, and sesame oil in the wok alongside
    traditional Peruvian ingredients. Lomo saltado — stir-fried sirloin with tomato, ají
    amarillo, and soy sauce over rice and fries simultaneously — is the other chifa preparation
    that defines this cuisine. The Entrañana (Argentine skirt steak, sometimes called arrachera)
    on Che Peru's Argentine side should be served thin-sliced after resting, with chimichurri
    made fresh; it is one of the most flavour-dense cuts on the cow and is typically undervalued
    in North American steak culture."""
),

'portuguese': p(
    """Two Portuguese kitchens in our verified-open feed. <b>Cafe Belem</b> on Oakwood Avenue
    in Little Jamaica is a Portuguese bakery-café — a second location of an established College
    Street fixture, named after the Belém neighbourhood of Lisbon where the original pastéis de
    nata recipe was developed. <b>Restaurante Requinte</b> in Corso Italia is a full sit-down
    restaurant. Both are on Dundas West or its surrounding corridors — the Little Portugal
    commercial strip remains the anchor. The community that built Little Portugal arrived in the
    1950s and 1960s and is now multiple generations deep in the city; the newer operations like
    Cafe Belem are serving a neighbourhood audience rather than building a new community hub.""",

    """Pastéis de nata at Cafe Belem are the reference point for this bakery's ambitions — the
    Belém name is a deliberate claim. The original Pastéis de Belém recipe (from the Monastery
    of the Jerónimos in Belém, Lisbon) is the standard against which all diaspora versions are
    measured: a shatteringly flaky pastry shell made from puff-style dough, a custard filling
    that is slightly runny in the center with a blistered and caramelized top, served warm and
    dusted with cinnamon. Cold pastéis de nata are a different eating experience; a kitchen that
    doesn't serve them warm is accepting a significant compromise. The custard should be slightly
    sweet, eggy, and not over-set.""",

    """Frango no churrasco — piri-piri charcoal chicken — is the preparation that defines
    Portuguese cooking in Toronto beyond the pastry counter. The birds should be marinated in
    a fresh piri-piri paste (bird's eye chillies, garlic, olive oil, lemon) rather than a
    commercial sauce, then cooked on a proper charcoal rotisserie with repeated basting to build
    the lacquered exterior. Bacalhau (salt cod, rehydrated through repeated soaking over days)
    is the ingredient that marks a kitchen treating Portuguese cooking as a serious tradition;
    thick-cut Portuguese-imported bacalhau performs differently from the thin dried salt cod
    available at Asian grocery stores. Caldo verde — kale and potato soup with Portuguese chouriço
    — is the soup that community members order as a comfort baseline."""
),

'senegalese': p(
    """<b>Pendafrica</b> on Oakwood Avenue in Little Jamaica is the only Senegalese kitchen in
    our verified-open feed — run by <b>Mame Penda Ndao</b>, who founded the restaurant around
    the principle that "food is more than a meal, it's a memory, a connection, a story from home."
    The menu: Djollof rice and fish ($30), Mafé — beef or chicken in peanut butter sauce ($25),
    fried fish ($35), with other Senegalese specialties available by prior order, plus catering.
    Open Tuesday through Saturday, 11am to 10pm. The Little Jamaica location on Oakwood between
    Eglinton West and St Clair places Pendafrica in a West African and Caribbean commercial strip
    that is the most natural embedding for a small Senegalese kitchen in Toronto.""",

    """Thiéboudienne — rice with whole stuffed fish, tomato broth, and vegetables cooked in a
    single pot — is Senegal's national dish and the thing Pendafrica is most directly competing
    on. The fish is stuffed with rof (a paste of parsley, garlic, and Dijon mustard) before
    cooking; the broth should be rich from the fish collagen and deeply savoury from the
    tomato base. The rice cooks in that broth, absorbing the fish and tomato flavour through the
    grain. The toasted bottom layer (similar to Persian tahdig, Korean nurungji) that develops
    from sustained heat at the end of the cook is the mark of a kitchen that has managed the
    pot through the full preparation. Mafé is the groundnut stew that crosses over most
    accessibly to non-Senegalese audiences.""",

    """Café Touba — Senegalese spiced coffee brewed with grains of selim (kinkeliba pepper, also
    called Negro pepper, a West African spice with an earthy, slightly anise-like flavour) and
    clove — is the community beverage that distinguishes a kitchen cooking for Senegalese diners
    from one approximating West African food for a general audience. Its presence on the menu at
    Pendafrica is the signal that Mame Penda Ndao is cooking from memory rather than for
    the market."""
),

'singaporean': p(
    """<b>Agak Agak</b> on Gerrard Street East in Moss Park — the name means "roughly" or
    "estimate" in Malay, a term that captures the intuitive, experience-based cooking approach
    of Singapore's hawker culture — is the only Singaporean-classified kitchen in our
    verified-open feed. It is anchored by laksa and Hainanese chicken rice, the two dishes that
    define the cuisine across Singapore's hawker centres. The Gerrard East location, adjacent to
    the original Little India strip, reaches a mixed East Asian and South Asian audience rather
    than a Singaporean community cluster; there is no Singaporean enclave in Toronto, and
    Agak Agak's operation is necessarily for a general audience drawn by the food itself.""",

    """Hainanese chicken rice is Singapore's national dish and the test for any kitchen claiming
    the cuisine. The chicken is poached whole in water with ginger and spring onion until just
    cooked — skin tender and slightly gelatinous, flesh pale and silky from the low temperature.
    The rice is then cooked in the poaching stock with chicken fat and pandan leaf until fragrant
    and slightly sticky. Served at room temperature with three sauces: fresh-blended chilli sauce
    with ginger and lime, ginger paste blended with oil, and dark soy. Each sauce serves a
    different function and none is optional. A kitchen serving the chicken over plain white rice
    or using commercial sauces is not executing this dish.""",

    """Laksa at Agak Agak requires freshly made rempah — the spice paste of shallots, galangal,
    lemongrass, dried chilli, and belacan (fermented shrimp paste) fried in oil until split (the
    fat separates from the paste when properly cooked). Rempah from a jar produces a flatter,
    less aromatic result. Char kway teow — flat rice noodles stir-fried with lap cheong, prawns,
    egg, bean sprouts, and dark soy — depends entirely on wok hei, the caramelization and
    smokiness that develop only at very high heat in a well-seasoned wok. Without wok hei, the
    dish is flat regardless of the quality of the ingredients."""
),

'south_asian': p(
    """Two South Asian kitchens in our feed using the broader regional label. <b>Kasturi Street
    Food & Sweets</b> on Danforth in Oakridge is a counter-service chaat and sweets operation
    in Scarborough, serving the overlapping Indian, Pakistani, and Bangladeshi communities along
    that corridor. <b>Crust 'N Crave Pizza</b> in Etobicoke runs a fusion format. Kasturi is
    the more relevant operation for understanding what "South Asian street food" means in a
    Toronto context: a counter serving pani puri, samosa chaat, bhel puri, and Indian mithai to
    a diaspora audience that eats these things daily rather than as a special occasion.""",

    """Pani puri — the hollow fried crisp filled with spiced chickpeas or potatoes and dunked
    into chilled spiced water — is the most evaluable item at a street food counter like Kasturi.
    The puris should be freshly fried (not stale, which makes them soggy before you can eat them)
    and thin enough to shatter rather than bend when bitten. The pani (spiced water) should be
    chilled, tart from tamarind, herbal from fresh mint and cilantro, and carry the black salt
    (kala namak) that gives the drink its sulphurous depth. A counter serving pre-made puris
    that have softened is making a compromise that the dish doesn't survive.""",

    """Mithai (Indian sweets) at the sweets counter is evaluated on freshness: gulab jamun
    (fried khoya dumplings in sugar syrup) should be freshly made from milk solids, not from
    powder, and syrup-soaked without being waterlogged. Barfi (compressed milk-solid sweets
    in various flavours) should have clean, present flavours — the khoya base should taste of
    reduced milk, not of commercial dairy powder. The standard set by community sweets counters
    in Scarborough is set by home cooking expectations; a counter operating below that level will
    be evaluated against what people's mothers make."""
),

'spanish': p(
    """<b>Churreria Calderon</b> on Baldwin Street in Kensington Market is the only
    Spanish-classified kitchen in our verified-open feed — a churro shop from a Catalan family,
    with a recipe passed down through generations of churro makers from Catalonia. Every morning
    they hand-make their churros fresh. The menu is focused: churros in several preparations,
    and Spanish-style thick hot chocolate — "rich and very thick," in the Spanish tradition where
    the chocolate is made to the consistency of a dipping sauce rather than a beverage. No other
    dishes. This is a specifically Spanish format and specifically Catalan in origin; there is
    no Spanish immigrant community corridor in Toronto, and the Kensington location serves
    a general audience.""",

    """Spanish churros are thinner and crispier than Mexican churros and are made from a
    choux-adjacent dough piped directly into hot oil. The Catalan family recipe at Calderon
    produces a churro that is crisp on the exterior with a slightly hollow, chewy interior —
    the result of the correct hydration ratio in the dough and the correct oil temperature.
    Underhydrated dough produces a dense churro; oil that is too cool produces a greasy one.
    The Spanish thick hot chocolate is made from dark chocolate and whole milk reduced together
    to the consistency of a custard sauce, not from cocoa powder — the dipping experience
    requires the chocolate to coat the churro rather than run off it.""",

    """Beyond churros, Spanish cooking in Toronto is accessed primarily through tapas and pintxos
    bars in King West, Ossington, and the Annex. Tortilla española — the Spanish potato and onion
    omelette — should be loose at the centre, not cooked through; a dry tortilla española is the
    most common and correctable failure in North American versions. Paella requires Valencia rice
    (bomba or similar short-grain), a paella pan over even direct heat, and a socarrat (the
    caramelized rice crust at the bottom) that develops naturally — not from browning agents. Jamón
    ibérico should be sliced to order from the bone rather than pre-sliced; the difference in
    texture between just-sliced and vacuum-stored ibérico is immediately perceptible."""
),

'sri_lankan': p(
    """Six Sri Lankan kitchens in our verified-open feed, all in Scarborough — the most
    geographically concentrated single-cuisine cluster in our data. The listings span the full
    arc of the borough: <b>Heba's Kitchen</b> on Lawrence East in Wexford (newest, 52 days),
    <b>Luxme Vilas</b> in Malvern, <b>Taste of Eelam</b> in Scarborough Village,
    <b>Blue Elephant Cuisine</b> in Clairlea-Birchmount, <b>Crab Ceylon</b> in Morningside
    Heights, and <b>Clay Steam Boat Spicy Kitchen</b> in Kennedy Park. The Warden-McNicoll
    Little Jaffna anchor remains the historic centre, but 40 years of Tamil Sri Lankan
    community-building has filled the entire borough. Heba's Kitchen operates as a
    Sri Lankan and South Indian counter with a stated commitment to cooking "with the same
    dedication as if we were serving our own family."  """,

    """Hoppers (appa in Sinhala, appam in Tamil) are the Sri Lankan preparation that most
    clearly distinguishes this cuisine from other South Asian cooking. The batter — fermented
    rice flour with coconut milk, a small amount of toddy or yeast for leavening — is cooked
    in a small hemispherical pan that produces a bowl-shaped crepe: crisp and lacy at the thin
    edges, soft and thick at the centre. An egg hopper has an egg broken into the bowl during
    cooking and the white set around it while the yolk stays runny. A hopper with thick,
    uniform edges rather than a crisp lace has not been made in the right pan. Crab Ceylon in
    Morningside Heights is the listing that most directly signals the most prestige item in
    Tamil Sri Lankan cooking: Jaffna crab curry.""",

    """Jaffna crab curry — made with Sri Lankan green crabs cooked in a roasted coconut and
    spice paste with pandan leaf, curry leaves, and tomato — is the prestige dish specific to
    the Tamil cooking tradition of northern Sri Lanka and is rarely found outside Tamil restaurants.
    The crab should be fresh (frozen crab in this preparation is detectable in the texture)
    and the spice paste roasted until dark and fragrant before the coconut milk is added. Kothu
    roti — chopped roti stir-fried on a heavy griddle with egg, vegetables, and curry sauce —
    is evaluated on whether it is cooked to order; the characteristic metal-scraper-on-griddle
    sound signals the dish is fresh. Pol sambol (fresh scraped coconut, red onion, Maldive fish
    flakes, lime, and chilli ground together) distinguishes Sri Lankan cooking from any other
    South Asian tradition; desiccated coconut does not substitute."""
),

'taiwanese': p(
    """Two Taiwanese kitchens in our verified-open feed. <b>Star Glow Boba & Coffee</b> on
    Bloor West in Dovercourt Village, the newer operation, runs a hybrid Taiwanese-Vietnamese
    menu with boba, milk tea, bingsu (Korean shaved ice), and bánh mì alongside the signature
    drinks — a format that reflects how Taiwanese boba culture has absorbed neighbouring Asian
    culinary influences in diaspora. <b>Jo's Cha</b> in Milliken (north Scarborough, near the
    Markham border) is in the northeast suburb where the Taiwanese-Canadian community is most
    concentrated. The Taiwanese-Canadian community arrived in significant numbers in the late
    1980s and 1990s and built commercial infrastructure in Markham and Richmond Hill that now
    represents some of the most complete Taiwanese food culture outside Taiwan.""",

    """Scallion pancakes (cong you bing) are the street food benchmark for Taiwanese cooking.
    The dough is rolled, spread with sesame oil and chopped scallion, rolled into a log, then
    coiled and rolled flat again — this laminating process creates the visible layers when the
    pancake is torn. A pancake laminated without layering has been folded rather than rolled in
    the correct technique. The dough should have a slight chew from the gluten development, and
    the scallion should be distributed through the layers rather than only on the surface. Beef
    noodle soup — Taiwan's signature dish — is evaluated on the broth: soy and doubanjiang
    (spicy fermented bean paste) base, slow-braised tendon and shank, the broth dark and
    deeply savoury.""",

    """Lu rou fan — braised pork belly over rice with five spice and soy — is the comfort staple:
    the braising liquid should be sweet, dark, and gelatinous from the pork collagen, the rice
    underneath absorbing the fat as it soaks. Boba tea originated in Tainan in the 1980s, and
    a kitchen operating in that tradition uses tapioca cooked to a specific chewiness (the boba
    should give slight resistance before yielding, not be uniformly soft) with a proper tea
    base. Star Glow's "Glow Tea" milk tea collection and its bingsu (shaved ice with fresh
    toppings) are the formats through which Taiwanese boba culture reaches Toronto's west-end
    café audience."""
),

'tamil': p(
    """Five Tamil kitchens in our verified-open feed, all in Scarborough.
    <b>Thirumalai Eats</b> in Malvern, licensed 25 days ago, is the newest.
    <b>Eelam Fusion</b> in Morningside Heights and <b>Aathavan Unavakam</b> in Milliken are
    the other recent additions. <b>Unavu Tamil Street Food</b> in Malvern and
    <b>Madurai Pandiyas Elite</b> in Dorset Park round out the feed. The cuisines span the
    range: Eelam Fusion brings a contemporary format; Madurai Pandiyas references Madurai,
    the South Indian city that anchors Tamil Nadu's own culinary tradition; Unavu (which means
    "food" in Tamil) is the street food format. Toronto has the largest Tamil diaspora community
    in the world outside South Asia.""",

    """Kothu roti is the street food that most defines casual Tamil eating. Godamba roti (the
    oil-layered flatbread) is torn into pieces on a heavy iron griddle and stir-fried with egg,
    vegetables, and curry sauce using a metal scraper. The sound of the scraper on the griddle
    is a community signal that the dish is being cooked to order — and the curry used as the
    sauce defines the kitchen. Kothu made with a Jaffna-style crab curry or a proper chicken
    varuval rather than a generic sauce indicates a kitchen working with its full pantry.
    Madurai Pandiyas' reference to Madurai signals South Indian Tamil rather than Sri Lankan
    Tamil cooking — a distinction that matters because the spice profiles, the rice preparations,
    and the vegetarian traditions are different.""",

    """Jaffna crab curry — Sri Lankan green crabs in a roasted coconut spice paste with pandan
    and curry leaves — is the prestige dish specific to Tamil Sri Lankan cooking and the item
    that most clearly marks a kitchen operating at the top of this category. Short eats (cutlets,
    fish rolls, vadai, string hopper parcels) are the bakery snack culture that complete a serious
    Tamil kitchen; their presence means the kitchen is feeding the community across the full day,
    not only at dinner. Salna, the thin curry-based gravy served alongside parotta (the layered
    flatbread), should be complex and slightly tart from tomato, with fennel and star anise in
    the spice base — a kitchen serving parotta with a generic curry sauce is missing
    the dish's architecture."""
),

'thai': p(
    """Eight Thai kitchens in our verified-open feed from the past year, with Leslieville as the
    most active sub-market: <b>Aroi Thai Dining & Bar</b> on Queen East (24 days ago) and
    <b>Lamoon Thai Kitchen and Coffee</b> also on Queen East. Aroi's menu has a northern Thai
    specialization — khao soi in both short rib and chicken versions, pomelo salad, braised short
    rib preparations — which is unusual in Toronto, where most Thai restaurants default to
    Bangkok-and-central cooking. <b>Som Tum Jinda</b> downtown is named for the dish that most
    distinguishes serious Thai kitchens. <b>Hua Hin</b> in Bloor West Village takes its name
    from the beach city south of Bangkok. <b>555 Boat Noodles</b> in Willowdale references the
    specific Thai preparation of pork or beef noodle soup from the canal boats of
    central Thailand.""",

    """Khao soi at Aroi is the northern Thai coconut curry noodle soup from Chiang Mai: a broth
    built on red curry paste (not yellow) and coconut milk with lemongrass and galangal, served
    with egg noodles both braised in the broth and fried crispy on top, pickled mustard greens
    and shallots alongside. The short rib version is Aroi's own application of the northern
    Thai format to a premium cut — the braise should yield the same tenderness as traditional
    khao soi chicken while adding the fat depth of the rib. Som tum (green papaya salad, the
    namesake of Som Tum Jinda) requires a mortar and pestle: bruising the shredded green papaya
    releases the texture, and the fermented fish sauce and dried shrimp ground into the dressing
    develop a depth that a pre-blended dressing cannot replicate.""",

    """Pad Thai is the dish most differentiated by technique in Toronto's Thai restaurant market.
    The tamarind sauce should be built from tamarind pulp dissolved in water, palm sugar, and
    fish sauce — not ketchup, which produces a sweet-and-sour flavour with none of the tartness
    tamarind provides. The noodles (flat rice noodles, sen lek) should be cooked by stir-frying
    at maximum wok heat; the egg fried directly on the wok surface and incorporated, not scrambled
    separately. Boat noodles at 555 Boat Noodles — the specific preparation from central Thailand
    where pork or beef broth is seasoned with pig's blood, giving the broth a dark, intensely
    savoury character — is one of the rarer Thai noodle formats in Toronto and signals a
    kitchen with depth."""
),

'tibetan': p(
    """<b>Highland Momo</b> on Islington Avenue in Elms-Old Rexdale is the only Tibetan kitchen
    currently in our verified-open feed — and its address is telling. Little Tibet in Parkdale,
    the six-block stretch of Queen Street West from Sorauren to Roncesvalles, is the most
    recognized Tibetan enclave in North America, built by the nearly 3,000 Tibetans who arrived
    in Toronto between 1998 and 2008 through a Canadian government resettlement program. Highland
    Momo is in Rexdale, not Parkdale — a western Etobicoke location that signals the Tibetan
    community's spread beyond its original Queen West anchor, into the diverse northwest
    suburbs where newer arrivals and second-generation Tibetan-Canadians are building
    separate commercial nodes.""",

    """Momos are the entry point and the test for any Tibetan kitchen. The dough should be
    thicker than a Chinese dumpling wrapper but thin enough to steam through; a momo with a
    doughy, undercooked centre has been wrapped too thick. The standard Toronto Tibetan momo
    filling is minced beef or lamb with ginger, garlic, cabbage, and a Tibetan spice blend;
    pork is less common than in Chinese dumpling traditions, reflecting the Himalayan context.
    Pan-fried momos (kothey) develop a bottom crust that is a categorically different eating
    experience from steamed; a kitchen offering both versions is demonstrating range. The
    dipping sauce — charred tomato, dried chilli, spices — should be house-made and smoky,
    not a commercial chilli sauce.""",

    """Thukpa, the hand-rolled flat noodle soup, is the daily staple that community members order
    and that non-Tibetan diners rarely know to ask for. The broth varies by season — clearer in
    summer, richer with yak or beef bone in winter. Butter tea (po cha), made from strong tea
    churned with salt and butter (yak butter traditionally, domestic butter in Toronto), is the
    warming community beverage; its absence from the menu signals a kitchen not primarily
    cooking for the Tibetan community. Shabaley — meat-filled fried bread patties — and tingmo
    (steamed bread served alongside curries) are the preparations that complete a serious
    Tibetan kitchen beyond the momo format that non-Tibetan diners know."""
),

'trinidadian': p(
    """Trinidadian restaurants in Toronto operate within the Caribbean corridor on Eglinton West,
    Jane Street, and Lawrence Avenue West, where Trinidadian-Canadian and Jamaican-Canadian
    communities have shared commercial infrastructure since the 1970s. The cuisine is distinct
    within the Caribbean in ways shaped by 19th-century Indian indentured labour migration:
    a significant portion of the Trinidadian population is Indo-Trinidadian, and the cooking
    reflects this in the centrality of curry, roti, and dal preparations that have no parallel
    in Jamaican or Barbadian cooking.""",

    """Doubles is the defining Trinidadian street food and unlike anything else in the Caribbean.
    Two baras (small flatbreads made from flour, turmeric, and yeast, fried until puffed) filled
    with curried chickpeas (channa), topped with pepper sauce, chadon beni (shadow beni — the
    Eryngium foetidum herb with a stronger, slightly metallic flavour distinct from cilantro),
    tamarind sauce, and cucumber. A proper bara should be puffed and slightly crisp on the outside
    while remaining soft inside; the channa should be a dry curry (not watery). The chadon beni
    is the ingredient that most specifically marks Trinidadian cooking — it grows in the
    Caribbean and is not the same herb as cilantro, though they are related.""",

    """Dhalpuri roti — ground split peas incorporated into the dough before cooking on a tawa —
    is the distinctly Trinidadian roti that differs from Indian paratha in texture and flavour.
    The curry inside a Trinidadian roti uses shadow beni, scotch bonnet, geera (cumin), and
    massala as its spice base — a specifically Trinidadian seasoning tradition. Bake and shark
    (fried shark sandwich with tamarind and pepper sauce) is the Maracas Bay beach food that
    has reached Toronto menus. Black cake — the dense rum-soaked Christmas fruit cake made from
    dried fruits macerated in rum and Angostura bitters for months — is the community marker
    that appears seasonally and signals a kitchen tracking the Trinidadian calendar."""
),

'turkish': p(
    """Ten Turkish kitchens in our verified-open feed from the past year, with Downsview in
    North York as the most active sub-market: <b>Kasap Doner and Grill</b>, <b>Doner G</b>,
    <b>Mega Kebab</b>, and <b>The Midye</b> have all licensed there recently.
    Kasap (which means "butcher" in Turkish) signals a kitchen with a meat-primary identity;
    Doner G is run by a Turkish family kitchen focused on charcoal cooking; The Midye takes its
    name from midye (Turkish stuffed mussels, the street food of Istanbul's Bosphorus waterfront).
    <b>La Vitrine Bar and Kitchen</b> in The Beaches and <b>Lezzet12 Shawarma</b> in Little
    Jamaica, the most recently licensed, extend the feed across the city. The Downsview cluster
    reflects Turkish-Canadian and broader Muslim immigrant residential density in that
    part of North York.""",

    """Köfte is the Turkish preparation most frequently made incorrectly in Toronto. Proper
    Turkish köfte uses hand-minced or coarsely ground lamb (not finely ground beef), mixed with
    grated onion and red pepper flakes, shaped onto a flat, wide skewer by hand to a specific
    tension, and cooked over charcoal. The char from charcoal against rendered lamb fat is
    categorically different from the same preparation on gas. Adana kebabı, the regional variant
    from Adana with lamb and isot (dried, smoked Urfa pepper), should be noticeably spicier than
    generic köfte and have a slightly looser texture from the higher fat content. Midye dolma
    (stuffed mussels, the Istanbul street food that The Midye takes its name from) are rice
    stuffed directly into the mussel shell, served cold — an unusual format in Toronto that
    signals a kitchen cooking from street-food specificity.""",

    """Pide, the Turkish flatbread boat, is where most Toronto Turkish kitchens diverge most in
    quality: the dough should be made in-house and the toppings should use kashar (the
    Turkish aged cow's milk cheese with a flavour distinct from mozzarella) rather than a generic
    substitute. Lahmacun — the thin flatbread with minced lamb topping — should be cooked at high
    temperature until the edges are crisp and the meat is fragrant, not pale and flexible. Manti
    (Turkish dumplings served with yogurt and browned butter with dried mint) should be small
    enough that dozens fit on a plate; the yogurt should be thick, room-temperature, and seasoned
    with garlic."""
),

'venezuelan': p(
    """<b>El Maracucho Toronto</b> on Wilson Avenue in Downsview is the only Venezuelan kitchen
    in our verified-open feed — named after El Maracucho, the informal nickname for a person
    from Maracaibo, Venezuela's second city and the capital of the oil-rich Zulia state. The
    Downsview location tracks Venezuelan-Canadian settlement in the northwest of the city.
    Venezuelan immigration to Toronto has accelerated substantially since 2015, when economic
    collapse and political instability began one of the largest displacement events in Latin
    American history; the community is building presence in Downsview, Etobicoke, and the
    west end alongside other Latin American and Caribbean communities.""",

    """Arepas are the preparation by which any Venezuelan kitchen is evaluated first. The dough
    should be made from masarepa (pre-cooked white or yellow cornmeal — Harina PAN is the
    most common brand, as specific to Venezuelan arepas as Maseca is to Mexican tortillas),
    hydrated to the right consistency, formed by hand into a disc about 2cm thick, and cooked
    on a budare (cast iron griddle) until the exterior develops a crust. The fillings that signal
    a kitchen with Venezuelan cultural knowledge: reina pepiada (shredded chicken with avocado
    and mayonnaise, named after the 1955 Miss Venezuela), pabellón (the national dish in arepa
    form — shredded beef, black beans, sweet plantain, white rice), and pelúa (shredded beef
    and melted yellow cheese).""",

    """Pabellón criollo as a full plate tests each component. Caraotas (black beans) should be
    cooked from dried, seasoned with papelón (raw cane sugar), garlic, and sofrito, whole rather
    than mushy. Carne mechada (shredded beef) should come from slow-braised flank or brisket,
    not ground meat. Tajadas (sweet plantain) require fully ripe, almost black plantain that
    caramelizes without bitterness. Tequeños — fried dough sticks filled with queso blanco or
    mozzarella as a substitute — are the party snack that appears at Venezuelan community events.
    Chicha (sweet rice milk) and papelón con limón (raw sugarcane juice with lime) identify a
    kitchen operating from its own tradition."""
),

'vietnamese': p(
    """Twenty-three Vietnamese kitchens in our feed from the past year — the most active large
    cuisine category in the city. The two newest: <b>And Bánh Mì</b> on Elm Street downtown
    (bread baked in-house daily, fillings and sauces made from scratch) and <b>Banh Mi Journey
    Yonge St</b> in North Toronto (part of a multi-location group also operating on Bloor West).
    The west end is where new Vietnamese licenses are currently most concentrated: The Junction
    has three operations (<b>Banh Mi Happy</b>, <b>Phin & Go Café</b>, <b>Baba Kitchen</b>),
    joined by <b>Botanic Coffee & Caphe</b> in Trinity-Bellwoods and <b>Vbow Pho Mi & More</b>
    in Little Italy. The Scarborough Birchmount-Huntingwood corridor is the established
    community anchor; the west end is where new licenses are landing.""",

    """Pho broth is the first test for any Vietnamese kitchen. Whole ginger and onion should be
    charred directly over flame before adding to the pot — this step produces the caramelized
    sweetness and colour that define the soup and cannot be achieved by simply adding raw
    aromatics. Bones (knuckle, marrow, and neck contribute different things) should simmer for
    12–18 hours with star anise, clove, cinnamon, coriander seed, and black cardamom. The result
    should be clear and deep amber — cloudiness means imprecise temperature management or
    insufficient skimming. And Bánh Mì's commitment to baking bread in-house daily is the
    direct answer to the question of what separates a serious bánh mì operation from one using
    commercial baguettes: the Vietnamese baguette uses a wheat-and-rice-flour mix that produces
    a thin, crackle-crisp crust and a lighter, airier interior than a standard French baguette.""",

    """Botanic Coffee & Caphe in Trinity-Bellwoods represents the Vietnamese café format that
    has become the leading edge of how Vietnamese culture reaches new Toronto neighbourhoods:
    Vietnamese coffee (cà phê) brewed through a phin filter with condensed milk, and café culture
    built around the ritual of slow-drip brewing. The phin filter produces a highly concentrated
    coffee that is then diluted with condensed milk (hot or over ice) to a sweetness and strength
    calibrated differently from espresso. Bún bò Huế — the lemongrass beef noodle soup from
    central Vietnam, spicier and more complex than pho — is the regional preparation that
    distinguishes kitchens with depth of repertoire. Com tấm (broken rice with grilled pork and
    fried egg) is the southern Vietnamese staple that community members order as the everyday meal."""
),

}

PATH = Path(__file__).resolve().parent / 'wire_editorial.json'
PATH.write_text(json.dumps(DATA, ensure_ascii=False, indent=2))
print(f'Written {len(DATA)} entries')

import re
for k, v in sorted(DATA.items()):
    w = len(re.sub('<[^>]+>', '', v).split())
    print(f'  {k:20s} {w}w')
