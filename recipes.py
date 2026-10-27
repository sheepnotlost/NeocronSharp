"""Saved recipe names/aliases; Neocron handles ingredients and quantities."""

from copy import deepcopy
from difflib import SequenceMatcher
import hashlib
import re

RECIPES = {
    "weaponpart_7": {"name": "Tangent Weaponpart 7", "category": "Weapon parts", "level": 35,
                     "ingredients": ("Trisol", "Metal D", "Arillium", "Solantium"),
                     "result_template": "constructed_weaponpart"},
    "weaponpart_9": {"name": "Tangent Weaponpart 9", "category": "Weapon parts", "level": 45,
                     "ingredients": ("Gamonin", "Metal D", "Solantium", "Strastin", "Tiberal"),
                     "result_template": "constructed_weaponpart"},
    "holy_heal": {"name": "Crahn Holy Heal", "category": "Spells", "level": 95,
                  "ingredients": tuple(f"Tangent Weaponpart {n}" for n in (9,7,6,5,4,1)),
                  "result_template": "constructed_holy_heal"},
}

RECIPES["weaponpart_7"]["aliases"]=("wp7","weaponpart 7")
RECIPES["weaponpart_9"]["aliases"]=("wp9","weaponpart 9")
RECIPES["holy_heal"]["aliases"]=("hh","holy heal")


def normalized(text):
    text=re.sub(r"\bwp\s*(\d+)\b",r"weaponpart \1",str(text).lower())
    return re.sub(r"[^a-z0-9]","",text)


def catalog(profile=None):
    recipes=deepcopy(RECIPES)
    hidden=(profile or {}).get("hidden_recipes",[])
    if not isinstance(hidden,list) or any(not isinstance(k,str) or k not in RECIPES for k in hidden) or len(set(hidden))!=len(hidden):
        raise ValueError("Invalid hidden built-in recipe list.")
    for key in hidden:recipes.pop(key)
    custom=(profile or {}).get("custom_recipes",{})
    if not isinstance(custom,dict) or len(custom)>500:
        raise ValueError("Custom recipes must be a list of at most 500 saved entries.")
    for key,value in custom.items():
        if not isinstance(key,str) or not key.startswith("custom_") or not isinstance(value,dict):
            raise ValueError("Invalid custom recipe.")
        name=value.get("name")
        aliases=value.get("aliases",[])
        if not isinstance(name,str) or not 2<=len(name.strip())<=120 or not normalized(name):
            raise ValueError("Recipe name must contain 2 to 120 characters.")
        if not isinstance(aliases,(list,tuple)) or len(aliases)>20 or any(
                not isinstance(a,str) or not 1<=len(a.strip())<=120 or not normalized(a) for a in aliases):
            raise ValueError("Recipe aliases must be names or shorthand, separated by commas.")
        recipes[key]={"name":name.strip(),"aliases":list(aliases),"category":"Custom recipe",
                      "level":None,"ingredients":(),"result_template":None}
    return recipes


def find_recipe(query, recipes):
    query=normalized(query)
    matches=[k for k,r in recipes.items() if query in [normalized(n) for n in (r["name"],*r.get("aliases",()))]]
    if len(matches)>1:
        raise ValueError("That name/shorthand matches more than one saved recipe. Use the full item name.")
    return matches[0] if matches else None


def add_recipe(profile,name,aliases=()):
    name=name.strip()
    # Built-ins can be removed from Job and restored by name/catalog selection.
    builtin=find_recipe(name,RECIPES)
    if builtin is not None:
        profile["hidden_recipes"]=[k for k in profile.get("hidden_recipes",[]) if k!=builtin]
        if profile.get("construction",{}).get("recipe") is None:profile["construction"]["recipe"]=builtin
        return builtin
    recipes=catalog(profile)
    existing=find_recipe(name,recipes)
    if existing is not None and existing in RECIPES:
        return existing
    key=existing or "custom_"+hashlib.sha256(normalized(name).encode()).hexdigest()[:16]
    aliases=[a.strip() for a in aliases if a.strip()]
    if existing is not None and normalized(name)!=normalized(recipes[existing]["name"]):
        # Typed text was one of its shorthands. Keep the full item name the
        # tooltip shows; renaming it to "ap1" would make it unmatchable.
        aliases.append(name);name=recipes[existing]["name"]
    entry={"name":name,"aliases":list(dict.fromkeys(aliases))}
    trial=deepcopy(profile)
    trial.setdefault("custom_recipes",{})[key]=entry
    updated=catalog(trial)
    for alias in (name,*entry["aliases"]):
        found=find_recipe(alias,updated)
        if found!=key:
            raise ValueError("That alias belongs to another recipe. Choose a different shorthand.")
    profile.setdefault("custom_recipes",{})[key]=entry
    if profile.get("construction",{}).get("recipe") is None:profile["construction"]["recipe"]=key
    return key


def remove_recipe(profile,key):
    """Remove a Job entry; the browse catalog stays intact."""
    book=catalog(profile)
    if key not in book:raise ValueError("Select a saved recipe to remove.")
    name=book[key]["name"]
    if key in RECIPES:profile.setdefault("hidden_recipes",[]).append(key)
    else:profile["custom_recipes"].pop(key)
    if profile.get("construction",{}).get("recipe")==key:
        profile["construction"]["recipe"]=next(iter(catalog(profile)),None)
    return name


def item_name_score(query, observed):
    # A different part number is never an OCR spelling correction.
    q=normalized(query);o=normalized(observed)
    if not q or not o or re.findall(r"\d+",q)!=re.findall(r"\d+",o):
        return 0.
    if o.endswith(q):return 1.
    words=re.findall(r"[a-z]+|\d+",observed.lower())
    if len(q)<=5 and not q.isdigit() and any(
            q=="".join(w if w.isdigit() else w[0] for w in words[-n:]) for n in range(1,len(words)+1)):
        return .95
    # OCR can confuse p/o, g/q, and r/n in the game's small font. Match the
    # complete suffix and require exact digits rather than fuzzy numbers.
    return max((SequenceMatcher(None,q,o[-n:]).ratio() for n in
                range(max(2,len(q)-3),min(len(o),len(q)+3)+1)),default=0.)


def identify_name(text, recipes):
    scores=sorted(((max(item_name_score(re.sub(r"\d+","",q) if r.get("ignore_numbers") else q,
                                       re.sub(r"\d+","",text) if r.get("ignore_numbers") else text)
                        for q in (r["name"],*r.get("aliases",()))),k)
                   for k,r in recipes.items()),reverse=True)
    if not scores:return "other"
    best,key=scores[0]
    if best>=.82 and (len(scores)==1 or best-scores[1][0]>=.06):return key
    return "unknown" if best>=.60 else "other"
