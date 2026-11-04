"""Expanded, deduplicated metadata within upload limits."""
import re
BASE_TAGS = ['Donald Trump', 'Trump', 'President Trump', 'MAGA', 'Make America Great Again', 'America First', 'Trump supporters', 'MAGA movement', 'MAGA patriots', 'Paul Revere Media', 'Christ is King', 'Jesus is King', 'God bless America', 'faith and freedom', 'Christian patriotism', 'American pride', 'American values', 'Americana', 'conservative commentary', 'political commentary', 'political humor', 'Trump memes', 'MAGA comedy', 'patriotic comedy', 'cartoon host', 'animated shorts', 'YouTube Shorts']
HASHTAGS = ['Trump', 'DonaldTrump', 'PresidentTrump', 'MAGA', 'MakeAmericaGreatAgain', 'AmericaFirst', 'TrumpSupporters', 'MAGAMovement', 'MAGAPatriots', 'GodBlessAmerica', 'ChristIsKing', 'JesusIsKing', 'ChristianFaith', 'FaithAndFreedom', 'Patriotism', 'AmericanPride', 'AmericanValues', 'AmericanFlag', 'StarsAndStripes', 'USA', 'Americana', 'Conservative', 'Conservatives', 'Republican', 'GOP', 'PoliticalCommentary', 'PoliticalHumor', 'PoliticalMemes', 'TrumpMemes', 'MAGAComedy', 'PatrioticComedy', 'Animation', 'AnimatedShorts', 'CartoonHost', 'Shorts', 'YouTubeShorts', 'PaulRevereMedia']

def enrich(content):
    result = dict(content)
    existing = result.get('tags', [])
    if not isinstance(existing, list):
        existing = []
    tags = []
    seen = set()
    cost = 0
    for value in existing + BASE_TAGS:
        if not isinstance(value, str):
            continue
        tag = value.strip().replace('<', '').replace('>', '')
        key = tag.casefold()
        if not tag or key in seen:
            continue
        extra = len(tag) + (2 if ' ' in tag else 0) + (1 if tags else 0)
        if cost + extra > 500:
            continue
        tags.append(tag)
        seen.add(key)
        cost += extra
    result['tags'] = tags
    description = result.get('description', '')
    if not isinstance(description, str):
        description = ''
    present = re.findall('(?<!\\w)#\\w+', description)
    known = {h[1:].casefold() for h in present}
    remaining = max(0, 60 - len(present))
    additions = []
    for tag in HASHTAGS:
        if tag.casefold() not in known and len(additions) < remaining:
            candidate = description + '\n\n' + ' '.join(additions + ['#' + tag])
            if len(candidate.encode('utf-8')) <= 5000:
                additions.append('#' + tag)
                known.add(tag.casefold())
    if additions:
        description += '\n\n' + ' '.join(additions)
    result['description'] = description
    print(f'[metadata] {len(tags)} tags; {len(present) + len(additions)} hashtags', flush=True)
    return result
