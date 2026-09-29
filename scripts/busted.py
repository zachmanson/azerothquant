"""A stand-in for busted, for a PC with no Lua: runs addon/spec on lupa's Lua 5.1.

CI runs the real busted (.github/workflows/ci.yml). This covers only what the specs use:
describe/it, before_each/after_each, and assert.are.equal / are.same / is_nil /
is_not_nil / is_true / is_false / matches / has_error. Each spec file gets a fresh Lua
state, like busted's default insulation.

    pip install lupa
    python scripts/busted.py                       # every addon/spec/*_spec.lua
    python scripts/busted.py addon/spec/scan_spec.lua
"""

import sys
from pathlib import Path

import lupa.lua51 as lua51

ADDON = Path(__file__).resolve().parent.parent / "addon"

# The busted API, in Lua. Tests are collected per file, then run in order.
BUSTED = r"""
local blocks, tests = {}, {}

function describe(name, fn)
  blocks[#blocks + 1] = { name = name, before = {}, after = {} }
  fn()
  blocks[#blocks] = nil
end
context = describe

local function snapshot()
  local copy = {}
  for i, b in ipairs(blocks) do copy[i] = b end
  return copy
end

function it(name, fn)
  local names = {}
  for _, b in ipairs(blocks) do names[#names + 1] = b.name end
  names[#names + 1] = name
  tests[#tests + 1] = { name = table.concat(names, " "), fn = fn, blocks = snapshot() }
end

function pending() end

function before_each(fn) local b = blocks[#blocks]; b.before[#b.before + 1] = fn end
function after_each(fn) local b = blocks[#blocks]; b.after[#b.after + 1] = fn end

local function show(v, depth)
  depth = depth or 0
  if type(v) == "string" then return string.format("%q", v) end
  if type(v) ~= "table" then return tostring(v) end
  if depth > 4 then return "{...}" end
  local keys = {}
  for k in pairs(v) do keys[#keys + 1] = k end
  table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
  local parts = {}
  for _, k in ipairs(keys) do
    parts[#parts + 1] = "[" .. show(k) .. "] = " .. show(v[k], depth + 1)
  end
  return "{ " .. table.concat(parts, ", ") .. " }"
end

local function same(a, b)
  if type(a) ~= "table" or type(b) ~= "table" then return a == b end
  for k, v in pairs(a) do if not same(v, b[k]) then return false end end
  for k in pairs(b) do if a[k] == nil then return false end end
  return true
end

local function check(ok, message)
  if not ok then error(message, 3) end
end

local function differ(e, a)
  return "Expected: " .. show(e) .. "\nPassed in: " .. show(a)
end

local function truthy(_, v, message, ...)
  if not v then error(message or "assertion failed!", 2) end
  return v, message, ...
end

assert = setmetatable({
  are = {
    equal = function(e, a) check(e == a, differ(e, a)) end,
    same = function(e, a) check(same(e, a), differ(e, a)) end,
  },
  are_not = {
    equal = function(e, a) check(e ~= a, "Expected not: " .. show(e)) end,
    same = function(e, a) check(not same(e, a), "Expected not: " .. show(e)) end,
  },
  is_nil = function(a) check(a == nil, "Expected nil, got " .. show(a)) end,
  is_not_nil = function(a) check(a ~= nil, "Expected a value, got nil") end,
  is_true = function(a) check(a == true, "Expected true, got " .. show(a)) end,
  is_false = function(a) check(a == false, "Expected false, got " .. show(a)) end,
  matches = function(p, s)
    check(type(s) == "string" and s:find(p) ~= nil, show(s) .. " doesn't match " .. show(p))
  end,
  has_error = function(fn) check(not pcall(fn), "Expected an error") end,
}, { __call = truthy })

function run_tests()
  local failures = {}
  for _, t in ipairs(tests) do
    local ok, err = xpcall(function()
      for _, b in ipairs(t.blocks) do for _, f in ipairs(b.before) do f() end end
      t.fn()
    end, debug.traceback)
    for i = #t.blocks, 1, -1 do
      for _, f in ipairs(t.blocks[i].after) do
        local ok2, err2 = pcall(f)
        if ok and not ok2 then ok, err = false, err2 end
      end
    end
    if not ok then failures[#failures + 1] = t.name .. "\n" .. tostring(err) end
  end
  return #tests, failures
end
"""


def run_file(path: Path) -> tuple[int, list[str]]:
    lua = lua51.LuaRuntime()
    lua.execute(f"package.path = {str(ADDON / 'AzerothQuant' / '?.lua')!r} .. ';' .. package.path")
    lua.execute(BUSTED)
    try:
        lua.execute(path.read_text(encoding="utf-8"))
    except lua51.LuaError as e:
        return 0, [f"{path.name} failed to load:\n{e}"]
    count, failures = lua.globals().run_tests()
    return count, list(failures.values())


def main(argv: list[str]) -> int:
    files = [Path(a).resolve() for a in argv] or sorted((ADDON / "spec").glob("*_spec.lua"))
    total, failed = 0, []
    for path in files:
        count, failures = run_file(path)
        total += count
        failed += [f"{path.name}: {f}" for f in failures]
    for f in failed:
        print(f"FAIL {f}\n")
    print(f"{total - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
