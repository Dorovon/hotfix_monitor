import os
import json
import pickle
import traceback
from collections import defaultdict
from struct import Struct, unpack_from
from urllib import request, error
from time import sleep

# the DBCache.bin files to monitor and images to use for them in the webhook
CACHE_FILES = {
  'Live': ('C:/Program Files (x86)/World of Warcraft/_retail_/Cache/ADB/enUS/DBCache.bin', 'https://cdn.discordapp.com/attachments/524387813060247553/963077048811786251/unknown.png'),
  'PTR': ('C:/Program Files (x86)/World of Warcraft/_ptr_/Cache/ADB/enUS/DBCache.bin', 'https://cdn.discordapp.com/attachments/524387813060247553/963077070114656306/unknown.png'),
  'Beta': ('C:/Program Files (x86)/World of Warcraft/_beta_/Cache/ADB/enUS/DBCache.bin', 'https://cdn.discordapp.com/attachments/524387813060247553/963077070114656306/unknown.png'),
}

# Each line of this file should be a discord webhook link to post changes to. These should look something like
WEBHOOK_FILE = os.path.join(os.path.split(__file__)[0], 'webhooks')

# Each line of this file is the name of a table to hash with SStrHash.
# If this file is ommi
DB_NAMES_FILE = os.path.join(os.path.split(__file__)[0], 'db_files')

# From https://wowdev.wiki/SStrHash
def SStrHash(string):
  def upper(c):
    if c == '/':
      return '\\'
    return c.upper()
  hash_table = [0x486E26EE, 0xDCAA16B3, 0xE1918EEF, 0x202DAFDB, 0x341C7DC7, 0x1C365303, 0x40EF2D37, 0x65FD5E49,
                0xD6057177, 0x904ECE93, 0x1C38024F, 0x98FD323B, 0xE3061AE7, 0xA39B0FA1, 0x9797F25F, 0xE4444563]
  seed = 0x7FED7FED
  shift = 0xEEEEEEEE
  for c in string:
    c = ord(upper(c))
    # In Python, mask with 0xFFFFFFFF in two places here so that the u32 math is correct.
    seed = (hash_table[c >> 4] - hash_table[c & 0xF]) & 0xFFFFFFFF ^ (shift + seed) & 0xFFFFFFFF
    shift = c + seed + 33 * shift + 3
  return seed if seed else 1

def do_webhook_request(req, data, try_count=1):
  try:
    request.urlopen(req, data=data)
  except error.HTTPError as e:
    if e.code == 429:
      if try_count <= 3:
        print('HTTP Error 429: Retrying...')
        sleep(1)
        do_webhook_request(req, data, try_count + 1)
      else:
        print(f'HTTP Error 429: Skipping webhook request after {try_count} failed attempts.')
    else:
      raise e

def post_webhook(username, content, avatar_url=None):
  if not os.path.exists(WEBHOOK_FILE):
    return
  try:
    with open(WEBHOOK_FILE, 'r') as f:
      data = {
        'username': username,
        'content': f'{content}',
      }
      if avatar_url != None:
        data['avatar_url'] = avatar_url
      for line in f.readlines():
        line = line.strip()
        if not line:
          continue
        req = request.Request(line.strip())
        req.add_header('User-agent', 'Mozilla/5.0')
        req.add_header('Content-Type', 'application/json')
        try:
          do_webhook_request(req, json.dumps(data).encode())
        except error.HTTPError:
          first_line = content.split('\n', 1)[0]
          data['content'] = f'{first_line}\nError: Unable to post full message.'
          do_webhook_request(req, json.dumps(data).encode())
  except Exception as e:
    # If posting the webhook fails for some reason, just print out the exception and continue execution.
    print(traceback.format_exc())

table_hashes = {}
if os.path.exists(DB_NAMES_FILE):
  with open(DB_NAMES_FILE, 'r') as f:
    for n in f.readlines():
      n = n.strip()
      table_hashes[SStrHash(n)] = n

status_type = {
  1: '(Add/Update Record)',
  2: '(Remove Record)',
  3: '(Remove Hotfixes)', # This also seems to frequently show up for server-side tables indicating that something about them changed!
  4: '(Not Public)',
}

class DBCache:
  def __init__(self, path, save_path='cache'):
    self.offset = 0
    with open(path, 'rb') as f:
      self.buffer = f.read()

    self.unpack_header()
    if not self.supported_version():
      return

    self.build_entries = set()
    self.build_cache_entries = set()
    self.all_entries = set()
    self.all_cache_entries = set()
    self.entries = set()
    self.cache_entries = set()
    if save_path != None:
      if not os.path.exists(save_path):
        os.makedirs(save_path)
      self.build_path = os.path.join(save_path, f'{self.build}.pickle')
      self.build_cache_path = os.path.join(save_path, f'{self.build}cache.pickle')
      self.all_path = os.path.join(save_path, 'all.pickle')
      self.all_cache_path = os.path.join(save_path, 'allcache.pickle')
      self.load_entries()

    self.new_entries = defaultdict(list)
    self.new_cache_entries = []
    self.new_build_entries = defaultdict(list)
    self.new_build_cache_entries = []
    while self.offset < len(self.buffer):
      self.unpack_entry()

    self.save_entries()

  def supported_version(self):
    if self.magic != b'XFTH' or not self.version in [7, 8]:
      return False
    return True

  def get_new_entry_messages(self, st=status_type):
    meta = ''
    messages = []
    new_pushes = 0
    new_hotfixes = 0
    new_cached = 0

    for index in sorted(self.new_entries):
      new_pushes += 1
      s = f'Push ID {index}\n'
      for name, record_id, data, status in self.new_entries[index]:
        new_hotfixes += 1
        s += f'  {name} {record_id} {st[status]}\n'
      messages.append(s)

    if self.new_cache_entries:
      s = 'Cache Entries\n'
      for name, record_id, data, status in self.new_cache_entries:
        new_cached += 1
        s += f'  {name} {record_id} {st[status]}\n'
      messages.append(s)

    old_pushes = len(self.new_build_entries) - new_pushes
    old_cached = len(self.new_build_cache_entries) - new_cached
    old_hotfixes = -new_hotfixes

    for index in sorted(self.new_build_entries):
      old_hotfixes += len(self.new_build_entries[index])

    if new_pushes or old_pushes:
      meta += f'  {len(self.entries)}/{len(self.build_entries)} hotfix entries known for this build found in DBCache.bin\n'

    if new_pushes:
      push = 'pushes' if new_pushes != 1 else 'push'
      entry = 'entries' if new_hotfixes != 1 else 'entry'
      meta += f'  {new_pushes} new hotfix {push} with {new_hotfixes} new {entry}\n'

    # Although this tool will not output details for known hotfixes, it is still
    # useful to know when hotfixes from one build are detected in another build.
    if old_pushes:
      push = 'pushes' if old_pushes != 1 else 'push'
      entry = 'entries' if old_hotfixes != 1 else 'entry'
      meta += f'  {old_pushes} hotfix {push} with {old_hotfixes} {entry} (old, but new for this build)\n'

    # Output newly detected cache entries; remove if you only ever want to see actual hotfixes.
    if new_cached:
      entry = 'entries' if new_cached != 1 else 'entry'
      meta += f'  {new_cached} new cache {entry}\n'

    # Old cache entries are common and not particularly useful to know about.
    # if old_cached:
    #   entry = 'entries' if old_cached != 1 else 'entry'
    #   meta += f'  {old_cached} cache {entry} (old, but new for this build)\n'

    if meta:
      messages.insert(0, f'Summary\n{meta}')

    return messages

  def load_entries(self):
    def load(path, attr):
      p = getattr(self, path)
      if os.path.exists(p):
        with open(p, 'rb') as f:
          setattr(self, attr, pickle.load(f))
    load('build_path', 'build_entries')
    load('build_cache_path', 'build_cache_entries')
    load('all_path', 'all_entries')
    load('all_cache_path', 'all_cache_entries')

  def save_entries(self):
    def save(path, attr):
      p = getattr(self, path)
      if p != None:
        with open(p, 'wb') as f:
          pickle.dump(getattr(self, attr), f)
    save('build_path', 'build_entries')
    save('build_cache_path', 'build_cache_entries')
    save('all_path', 'all_entries')
    save('all_cache_path', 'all_cache_entries')

  def get_header(self):
    return f'{self.magic.decode()} v{self.version} {self.build}'

  def unpack(self, unpacker_format):
    unpacker = Struct(unpacker_format)
    values = unpacker.unpack_from(self.buffer, self.offset)
    self.offset += unpacker.size
    return values

  def unpack_bytes(self, size):
    if size > 0:
      data = self.buffer[self.offset:self.offset + size]
      self.offset += size
    else:
      data = b''
    return data

  def unpack_header(self):
    self.magic, self.version, self.build, *verification_hash = self.unpack('<4sII32B')

  def unpack_entry(self):
    # This exception for version 8 applies to all 9.1.0 builds, but it is not possible to detect the full version from just the hotfix file.
    if self.version == 7 or self.version == 8 and self.build in [39291]:
      magic, index, table_hash, record_id, data_size, status, *_ = self.unpack('<4siIIIB3x')
    elif self.version >= 8:
      magic, index, _, table_hash, record_id, data_size, status, *_ = self.unpack('<4siIIIIB3x')
    data = self.unpack_bytes(data_size)
    table_name = table_hashes[table_hash] if table_hash in table_hashes else 'unk_' + str(table_hash)
    entry = (index, table_name, record_id, status, data)
    if index != -1: # hotfix entries have positive indices
      self.entries.add(entry)
      if not entry in self.all_entries:
        self.all_entries.add(entry)
        self.new_entries[index].append((table_name, record_id, data, status))
      if not entry in self.build_entries:
        self.build_entries.add(entry)
        self.new_build_entries[index].append((table_name, record_id, data, status))
    else: # cache entries have an index of -1
      self.cache_entries.add(entry)
      if not entry in self.all_cache_entries:
        self.all_cache_entries.add(entry)
        self.new_cache_entries.append((table_name, record_id, data, status))
      if not entry in self.build_cache_entries:
        self.build_cache_entries.add(entry)
        self.new_build_cache_entries.append((table_name, record_id, data, status))

def process_cache(name, path, icon=None, local=False):
  dbcache = DBCache(path)

  def post(message):
    message = message.rstrip()
    print(message)
    if not local:
      post_webhook(f'Build {dbcache.build}', message, avatar_url=icon)

  print(f'checking {name} (build {dbcache.build})')
  if not dbcache.supported_version():
    post(f'Unsupported DBCache.bin file: {dbcache.get_header()}')
    return

  for s in dbcache.get_new_entry_messages():
    post(s)

# for mass processing archived DBCache files stored in numeric directories
# local=True means that "new" entries will not be posted to webhooks.
def process_all(path, local=True):
  builds = sorted([int(b) for b in os.listdir(path) if b.isdecimal()])
  for b in builds:
    process_cache(b, os.path.join(path, str(b), 'DBCache.bin'), local=local)

# utility for removing/modifying data that is stored in the wrong format
# generally not needed unless changes to other code break something
def clean(root='cache'):
  for p in os.listdir(root):
    path = os.path.join(root, p)
    new_entries = set()
    with open(path, 'rb') as f:
      entries = pickle.load(f)
      for entry in entries:
        index, table_name, record_id, status, data = entry
        # index must be postive for hotfix entries or -1 for cached data, so remove entries with any other values
        if index >= -1:
          if type(data) == str:
             # data should be stored as bytes; if it was incorrectly stored as a string convert it to bytes
            entry = (index, table_name, record_id, status, data.encode())
          else:
            new_entries.add(entry)
      if len(entries) != len(new_entries):
        print(f'{p} {len(entries)} Entries -> {len(new_entries)} Cleaned Entries')
    with open(path, 'wb') as f:
      pickle.dump(new_entries, f)

if __name__ == '__main__':
  # the modification timestamp for the last time each cache file was processed
  times = {}

  # TODO: It would probably be better to handle this with events that fire when a file changes,
  # but polling just a few files works well enough and helps to minimize required dependencies.
  while True:
    for name in CACHE_FILES:
      path, icon = CACHE_FILES[name]
      if not os.path.exists(path):
        continue

      t = os.stat(path).st_mtime
      if name in times and times[name] == t:
        continue

      times[name] = t
      process_cache(name, path, icon)

    sleep(1)
