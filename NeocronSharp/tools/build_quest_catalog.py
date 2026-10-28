"""Build a local, read-only index of quest evidence from a Neocron installation.

Usage: python build_quest_catalog.py <game directory> <output json>
Uses only the standard library. It never executes the game's scripts.
"""
import csv
import io
import json
import re
import sys
import zlib
from pathlib import Path

MAGIC = bytes.fromhex('0af73d8884758493bdeffdab')

def decode(path):
    raw = path.read_bytes()
    if raw.startswith(MAGIC):
        size = int.from_bytes(raw[12:16], 'little')
        if size > 32_000_000:
            raise ValueError(f'oversized {path}')
        raw = zlib.decompress(raw[16:])
        if len(raw) != size:
            raise ValueError(f'bad length {path}')
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw.decode('latin-1')

def rows(game, name):
    return [x for x in csv.DictReader(io.StringIO(decode(game / 'definitions' / ('pak_' + name + '.csv')))) if x['Enabled'] == '1']

def unquote(value):
    value = value.strip()
    if value.startswith('"'):
        try:
            return json.loads(value)
        except ValueError:
            pass
    return value.split(' #', 1)[0].strip(" '\"")

def friendly(value):
    return re.sub(r'[_\.]+', ' ', value).strip().capitalize()

def quoted(value):
    """Read a literal double-quoted string, leaving expressions unresolved."""
    match = re.match(r'\s*("(?:\\.|[^"\\])*")', value)
    if not match or value[match.end():].lstrip().startswith('..'):
        return ''
    try:
        return json.loads(match.group(1)).strip()
    except ValueError:
        return match.group(1)[1:-1].replace('\\n', '\n').replace('\\"', '"').strip()

def yaml_dialogue(lines, key):
    # Restrict to the dialogue group associated with this mission's source NPC.
    start = next((i for i, s in enumerate(lines) if s.strip() == 'dialogue:' and not s.startswith(' ')), None)
    if start is None or not key:
        return ''
    candidates = [(i, m.group(1)) for i, s in enumerate(lines[start+1:], start+1)
        if (m := re.match(r'^  ([^\s:]+):\s*(?:#.*)?$', s)) and (key == m.group(1) or key.startswith(m.group(1) + '.'))]
    if not candidates:
        return ''
    begin, group = max(candidates, key=lambda pair: len(pair[1]))
    end = next((i for i in range(begin+1, len(lines)) if re.match(r'^  [^\s:]+:', lines[i]) or re.match(r'^\S[^:]*:', lines[i])), len(lines))
    mode = ''
    result = []
    for line in lines[begin+1:end]:
        stripped = line.strip()
        if re.match(r'^\s{6}say:', line): mode = 'NPC'
        elif re.match(r'^\s{6}answer:', line): mode = 'Your response'
        elif re.match(r'^\s{4}[^\s:]+:', line): mode = ''
        if not mode: continue
        m = re.match(r'^\s*-\s*(?:text:\s*)?(".*)$', line) or re.match(r'^\s*text:\s*(".*)$', line)
        if m and (text := quoted(m.group(1))): result.append(f'{mode}: {text}')
    return '\n\n'.join(result)

def lua_dialogue(lines):
    result = []
    for line in lines:
        if line.lstrip().startswith('--'): continue
        m = re.search(r'\b(SAY|SAYSPEECH|ANSWER|ANSWERSPEECH)\s*\(\s*(.*)$', line, re.I)
        if m and (text := quoted(m.group(2))):
            result.append(('Your response' if m.group(1).upper().startswith('ANSWER') else 'NPC') + ': ' + text)
    return '\n\n'.join(result)

def build(game):
    items = {r['EntryId']: r['Name'] for r in rows(game, 'items')}
    characters = {r['EntryId']: r['Name'].replace('\\n', ' / ') for r in rows(game, 'characters')}
    families = {r['EntryId']: r['Name'] for r in rows(game, 'npcfamilies')}
    npc_rows = rows(game, 'npcs')
    npcs = {r['EntryId']: characters.get(r['ModelTargetValue'], '') for r in npc_rows if r['ModelTargetType'] == '1'}
    script_paths = {r['Name'].lower(): r['FilePath'].replace('\\', '/').lower() for r in rows(game, 'scripts')}
    script_npcs = {}
    for npc in npc_rows:
        path = script_paths.get(npc['DialogScript'].lower())
        name = npcs.get(npc['EntryId'])
        if path and name:
            script_npcs.setdefault(path, []).append((npc['EntryId'], name))
    out = []
    errors = []
    scripts = game / 'scripts'
    def named_blocks(lines):
        groups = []
        for line in lines:
            m = re.match(r'^      ([\w-]+):\s*(?:#.*)?$', line)
            if m:
                groups.append([m.group(1), {}])
            elif groups and (m := re.match(r'^        ([\w-]+):\s*(.+?)\s*$', line)):
                groups[-1][1][m.group(1)] = unquote(m.group(2))
        return groups

    def structured_details(fields, npcname):
        chunks = []
        source = '\n'.join(fields.get('source', []))
        loc = re.search(r'(?im)^\s*type:\s*\d+\s*#\s*(.+)$', source)
        chunks.append('CONTACT\n' + (npcname or 'Not identified in this file.') + (f'\nLocation clue: {loc.group(1).strip()}' if loc else ''))
        if fields.get('repeat'):
            rep = unquote(fields['repeat'][0]); chunks.append('REPEAT\n' + {'once':'One time', 'unlimited':'Repeatable'}.get(rep, friendly(rep)))
        if fields.get('difficulty'):
            chunks.append('DIFFICULTY\n' + unquote(fields['difficulty'][0]))
        available = fields.get('available', [])
        if available:
            prereqs = []
            completed_indent = None
            for line in available:
                if re.match(r'^\s*completed:\s*$', line): completed_indent = len(line) - len(line.lstrip()); continue
                if completed_indent is not None:
                    indent = len(line) - len(line.lstrip())
                    if line.strip() and indent <= completed_indent: completed_indent = None
                    elif (m := re.match(r'^\s*-\s*([\w.\-]+)', line)): prereqs.append('Complete ' + m.group(1))
            chunks.append('POSSIBLE PREREQUISITES\n' + ('\n'.join('• ' + p for p in prereqs) + '\nOther conditions may also apply.' if prereqs else 'Conditions are present in the source; see Original source for details.'))
        aliases = {'source': npcname or 'the quest contact'}
        for name, data in named_blocks(fields.get('npcs', [])):
            aliases[name] = npcs.get(data.get('type',''), friendly(name)) or friendly(name)
        objectives = named_blocks(fields.get('objectives', []))
        if objectives:
            formatted = []
            for key, data in objectives:
                typ = data.get('type', '')
                count = data.get('count', '')
                quantity = f'{count} × ' if count else ''
                item = items.get(data.get('item', ''), 'item #' + data.get('item', '?'))
                npc = npcs.get(data.get('npc_type', ''), 'NPC #' + data.get('npc_type', '?'))
                named = aliases.get(data.get('npc', ''), friendly(data.get('npc', '')) or 'the contact')
                family = families.get(data.get('family', ''), 'family #' + data.get('family', '?'))
                if typ == 'collect_item': action = f'Collect {quantity}{item}'
                elif typ == 'kill_npc_type': action = f'Defeat {quantity}{npc}'
                elif typ == 'kill_npc_family': action = f'Defeat {quantity}{family}'
                elif typ == 'loot_npc_type': action = f'Loot {npc}'
                elif typ == 'kill_npc': action = f'Defeat {named}'
                elif typ == 'dialog_trigger': action = f'Talk to {named}'
                elif typ == 'tradeskill_use': action = f'Use a tradeskill on {item}'
                else: action = friendly(key) + (f' ({friendly(typ)})' if typ else '')
                if data.get('overwrite_description'): action += '\n    Note: ' + data['overwrite_description']
                formatted.append('• ' + action)
            chunks.append('OBJECTIVES\n' + '\n'.join(formatted))
        reward_lines = fields.get('rewards', [])
        rewards = []
        for line in reward_lines:
            if m := re.match(r'^\s*(money|exp|skill_exp):\s*(\d+)', line):
                label = {'money':'credits','exp':'experience','skill_exp':'skill experience'}[m.group(1)]
                rewards.append(f'{int(m.group(2)):,} {label}')
            elif m := re.match(r'^\s*-\s*type:\s*(\d+)', line):
                rewards.append(items.get(m.group(1), 'Item #' + m.group(1)))
        if reward_lines:
            chunks.append('REWARDS\n' + ('\n'.join('• ' + r for r in rewards) if rewards else 'See Original source for reward details.'))
        return '\n\n'.join(chunks)

    for p in sorted((scripts / 'yaml').rglob('*.yaml')):
        if p.name.lower().endswith('_de.yaml'):
            continue
        try:
            source = decode(p).replace('\r\n', '\n').replace('\r', '\n')
            lines = source.splitlines()
            rel = p.relative_to(game).as_posix()
            in_missions = False
            blocks = []
            start = None
            for i, line in enumerate(lines + ['end_of_file:']):
                if re.match(r'^\S[^:]*:', line):
                    if start is not None:
                        blocks.append((start, i)); start = None
                    in_missions = line.strip() == 'missions:'
                elif in_missions and re.match(r'^  [^\s][^:]*:\s*(?:#.*)?$', line):
                    if start is not None: blocks.append((start, i))
                    start = i
            # Keep the whole source so the selected mission and its dialogue
            # can both be reviewed with their original line numbers.
            dialogue = '\n'.join(f'{n:4}  {s}' for n,s in enumerate(lines,1))
            for a, b in blocks:
                block = lines[a:b]
                key = block[0].strip().rstrip(':')
                fields = {}
                current = None
                for line in block[1:]:
                    m = re.match(r'^    ([\w-]+):\s*(.*)$', line)
                    if m:
                        current = m.group(1); fields.setdefault(current, [])
                        if m.group(2): fields[current].append(m.group(2))
                    elif current:
                        fields[current].append(line)
                def field(name): return '\n'.join(fields.get(name, [])).strip()
                title = unquote(field('title')) or key
                description = unquote(field('description'))
                source_npc = re.search(r'(?m)^\s+type:\s*(\d+)', field('source'))
                npcname = npcs.get(source_npc.group(1), '') if source_npc else ''
                details = structured_details(fields, npcname)
                dialogue_key = re.search(r'(?m)^\s*dialogue:\s*([\w.\-]+)', field('source'))
                conversation = yaml_dialogue(lines, dialogue_key.group(1)) if dialogue_key else ''
                out.append(dict(id=key, title=title, category='Structured mission', contact=npcname, description=description,
                    details=details, conversation=conversation, dialogue=dialogue, source=rel, line=a+1,
                    note='Structured client mission. Dialogue shown is from this file and may include other missions. Availability and progress are not live.'))
        except (OSError, ValueError, zlib.error) as e:
            errors.append(f'{p}: {e}')

    mission_call = re.compile(r'\b(?:STARTMISSION|CANDOEPICRUN|GIVEQUESTITEM|GIVESPECIALITEM|GETMISSIONSTATUS|SETMISSIONSTATUS|EPICRUNFINISHED)\s*\(', re.I)
    for p in sorted((scripts / 'lua').rglob('*.lua')):
        try:
            source = decode(p).replace('\r\n', '\n').replace('\r', '\n')
            if not mission_call.search(source): continue
            lines = source.splitlines()
            rel = p.relative_to(game).as_posix()
            # Resolve only numeric literals and globally named constants assigned
            # once in the entire file. Expressions and reassigned variables stay unknown.
            assignments = {}
            for line in lines:
                if match := re.match(r'^\s*(?:local\s+)?([A-Z][A-Z0-9_]*)\s*=\s*([^\-]+)', line):
                    assignments.setdefault(match.group(1), []).append(match.group(2).strip())
            constants = {name: values[0] for name, values in assignments.items() if len(values) == 1 and values[0].isdigit()}
            taken, given = set(), set()
            for n, line in enumerate(lines, 1):
                match = re.search(r'\b(GIVEITEM|GIVEITEMWITHSLOTS|GIVEQUESTITEM|GIVESPECIALITEM|TAKEITEM|TAKEITEMCNT|TAKESPECIALITEMCNT)\s*\(\s*([A-Za-z_][A-Za-z_0-9]*|\d+)\s*[,)]', line, re.I)
                if match and not line.lstrip().startswith('--'):
                    item_id = constants.get(match.group(2), match.group(2))
                    if item_id in items: (taken if match.group(1).upper().startswith('TAKE') else given).add(items[item_id])
            canonical = rel.replace('/pak_', '/').lower()
            contacts = script_npcs.get(canonical, [])
            contact = ', '.join(dict.fromkeys(name for _,name in contacts))
            if len(contact) > 200: contact = contact[:197] + '…'
            # Preserve the complete branch context: conditions and neighboring lines
            # are essential to interpreting a dialogue choice or item operation.
            evidence = [f'{n:4}  {s}' for n,s in enumerate(lines,1)]
            title = re.sub(r'(?<=[A-Za-z])(?=\d)', ' ', re.sub(r'[_-]+', ' ', p.stem.removeprefix('pak_'))).strip().title()
            title_comment = re.search(r'(?im)^[ \t]*--[ \t]*(?:description|desc)[ \t]*:[ \t]*([^\r\n]{8,120}?)[ \t]*$', '\n'.join(lines[:50]))
            if title_comment and not title_comment.group(1).lstrip().startswith('--'): title = title_comment.group(1).strip()
            conversation = lua_dialogue(lines)
            details = []
            details.append('CONTACT\n' + (contact or 'Not identified in the client NPC definitions.'))
            if taken: details.append('ITEMS THE NPC MAY ASK FOR\n' + '\n'.join('• ' + item for item in sorted(taken)))
            if given: details.append('ITEMS THE NPC MAY GIVE\n' + '\n'.join('• ' + item for item in sorted(given)))
            money = set()
            for match in re.finditer(r'(?m)^\s*TAKEMONEY\s*\(\s*([A-Za-z_][A-Za-z_0-9]*|\d+)\s*\)', source, re.I):
                amount = constants.get(match.group(1), match.group(1))
                if amount.isdigit(): money.add(int(amount))
            if money: details.append('POSSIBLE COST\n' + '\n'.join(f'• {amount:,} credits (depends on choice)' for amount in sorted(money)))
            gates = []
            for gate, label in [('GETBASERANK','base rank'), ('GETWOCSKILL','Wisdom of Ceres skill')]:
                for match in re.finditer(r'\b' + gate + r'\s*\(\s*\)\s*if\s*\(\s*result\s*(>=|<=|==|>|<)\s*(\d+)\s*\)', source, re.I):
                    comparison = {'>=':'at least', '>':'more than', '==':'equal to', '<=':'at most', '<':'less than'}[match.group(1)]
                    gates.append(f'Checks {label}: {comparison} {match.group(2)}; outcome depends on the dialogue branch.')
            if gates: details.append('CONDITIONS FOUND\n' + '\n'.join('• ' + x for x in dict.fromkeys(gates)))
            clues = []
            messages = conversation.split('\n\n')
            messages.sort(key=lambda m: not bool(re.search(r'\b(?:sector|sektor)\s+[A-Z][- ]?\d', m, re.I)))
            for message in messages:
                if re.search(r'\b(?:sector|sektor|plaza|outzone|wastelands|pepper park|tech haven)\b', message, re.I) and len(clues) < 6:
                    clues.append(message.removeprefix('NPC: ').removeprefix('Your response: '))
            if clues: details.append('POSSIBLE LOCATION CLUES IN DIALOGUE\n' + '\n\n'.join('• ' + clue for clue in dict.fromkeys(clues)))
            details.append('This script can include several missions and alternative outcomes. Read the dialogue for context; items listed may apply only to particular choices.')
            out.append(dict(id=rel, title=title, category='Lua quest script', contact=contact, description='Quest-related dialogue from the game files.',
                details='\n\n'.join(details), conversation=conversation, dialogue='\n'.join(evidence), source=rel, line=1,
                note='Extracted script evidence, not a validated walkthrough. Lines can be conditional, refer to alternatives, or belong to multiple missions.'))
        except (OSError, ValueError, zlib.error) as e:
            errors.append(f'{p}: {e}')
    mission_titles = {e['id']: e['title'] for e in out if e['category'] == 'Structured mission'}
    for entry in out:
        if entry['category'] == 'Structured mission':
            entry['details'] = re.sub(r'(?m)^• Complete ([\w.\-]+)$', lambda m: '• Complete ' + mission_titles.get(m.group(1), m.group(1)), entry['details'])
    return {'version': 1, 'entries': out, 'issues': errors}

if __name__ == '__main__':
    catalog = build(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(json.dumps(catalog, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    from collections import Counter
    print('Entries:', dict(Counter(x['category'] for x in catalog['entries'])), 'Issues:', len(catalog['issues']))
    for issue in catalog['issues'][:10]: print(issue)
