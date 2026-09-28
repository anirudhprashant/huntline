"""Where a job is, and what each country needs for a foreign hire.

Each entry gives a location regex, the country codes the job APIs expect, and the
phrases that mean "we will not hire you without existing work rights".
"""
import re

COUNTRIES = {
    "canada": {
        "loc": r"canada|ontario|british columbia|alberta|qu[eé]bec|manitoba|saskatchewan|nova scotia|"
               r"new brunswick|newfoundland|prince edward|toronto|vancouver|montr[eé]al|calgary|ottawa|"
               r"edmonton|winnipeg|halifax|waterloo|kitchener|victoria|mississauga|burnaby",
        "adzuna": "ca", "indeed": "Canada", "jobspy_location": "Canada",
        "neg": r"(citizens?|permanent residents?) only|must (already )?be (legally )?(eligible|authori[sz]ed) to work in canada|"
               r"(fluent|bilingual)[^.]{0,40}french|french[^.]{0,30}(required|mandatory|essential)",
    },
    "uk": {
        "loc": r"united kingdom|\buk\b|england|scotland|wales|northern ireland|london|manchester|birmingham|"
               r"leeds|glasgow|edinburgh|bristol|liverpool|sheffield|cambridge|oxford|cardiff|belfast|"
               r"nottingham|newcastle|reading|brighton",
        "adzuna": "gb", "indeed": "UK", "jobspy_location": "United Kingdom",
        "neg": r"right to work in the uk (is )?(required|essential|a must)|must (already )?have (the )?right to work",
    },
    "netherlands": {
        "loc": r"netherlands|nederland|holland|amsterdam|rotterdam|utrecht|eindhoven|the hague|den haag|"
               r"delft|groningen|leiden|haarlem|tilburg|nijmegen|breda|almere|amersfoort|arnhem|maastricht",
        "adzuna": "nl", "indeed": "Netherlands", "jobspy_location": "Netherlands",
        "neg": r"(fluent|native)[^.]{0,30}dutch|dutch[^.]{0,30}(required|mandatory|essential|must)|"
               r"(eu|eea) (citizens?|work permit|passport) (only|required)",
    },
    "germany": {
        "loc": r"germany|deutschland|berlin|munich|m[uü]nchen|hamburg|frankfurt|cologne|k[oö]ln|stuttgart|"
               r"d[uü]sseldorf|leipzig",
        "adzuna": "de", "indeed": "Germany", "jobspy_location": "Germany",
        "neg": r"(fluent|native|flie[sß]end)[^.]{0,30}(german|deutsch)|german[^.]{0,30}(required|mandatory|essential|must)",
    },
    "ireland": {
        "loc": r"ireland|dublin|cork|galway|limerick",
        "adzuna": None, "indeed": "Ireland", "jobspy_location": "Ireland",
        "neg": r"must (already )?have (the )?(right|eligibility) to work in ireland",
    },
    "usa": {
        "loc": r"united states|\busa?\b|new york|san francisco|seattle|austin|boston|chicago|los angeles|denver|"
               r"\b(ny|ca|wa|tx|ma|il|co)\b",
        "adzuna": "us", "indeed": "USA", "jobspy_location": "United States",
        "neg": r"must be (a )?(us|u\.s\.) citizen|green card|authori[sz]ed to work in the (us|united states) without",
    },
    "australia": {
        "loc": r"australia|sydney|melbourne|brisbane|perth|adelaide|canberra",
        "adzuna": "au", "indeed": "Australia", "jobspy_location": "Australia",
        "neg": r"(australian )?(citizens?|permanent residents?) only|must have (full )?working rights",
    },
    "india": {
        "loc": r"india|bengaluru|bangalore|mumbai|delhi|gurgaon|gurugram|noida|hyderabad|pune|chennai|kolkata|"
               r"ahmedabad|jaipur|kochi",
        "adzuna": "in", "indeed": "India", "jobspy_location": "India",
        "neg": r"$^",
    },
    "remote": {
        "loc": r"\bremote\b|anywhere|worldwide|work from home|distributed",
        "adzuna": None, "indeed": None, "jobspy_location": None,
        "neg": r"$^",
    },
}

# Phrases that rule a posting out for anyone needing sponsorship, in any country.
NEG_ANY = (r"(no|not|unable to|cannot|can ?not|can'?t|won'?t|will not|do not|does not|don'?t|doesn'?t)"
           r"\s+(\w+\s+){0,3}(sponsor|sponsorship|lmia|work permits?|visas?)\b|"
           r"security clearance|without (the need for )?(visa )?sponsorship")

# Phrases that say the employer will help with a visa.
POS_ANY = (r"visa sponsorship|sponsorship (is )?(available|provided|offered|support)|(will|can|able to|happy to) sponsor|"
           r"\blmia\b|work permit (support|assistance|sponsorship)|relocation (package|assistance|support)|"
           r"global talent stream|immigration support|open to international|skilled worker visa|"
           r"certificate of sponsorship|highly skilled migrant|kennismigrant|blue card")


def loc_regex(names):
    pats = [COUNTRIES[n]["loc"] for n in names if n in COUNTRIES]
    return re.compile("|".join(pats), re.I) if pats else None


def country_of(location, names):
    """First of your countries this location is in. "Remote (US only)" is not remote for you
    unless you also chose usa, so remote jobs tied to a country you didn't pick are dropped."""
    loc = location or ""
    for n in names:
        if n != "remote" and n in COUNTRIES and re.search(COUNTRIES[n]["loc"], loc, re.I):
            return n
    if "remote" in names and re.search(COUNTRIES["remote"]["loc"], loc, re.I):
        others = [c for c in COUNTRIES if c not in names and c != "remote"]
        if not any(re.search(COUNTRIES[c]["loc"], loc, re.I) for c in others):
            return "remote"
    return ""
