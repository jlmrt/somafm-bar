local mp = require 'mp'
local utils = require 'mp.utils'

local status_file = os.getenv('SOMA_STATUS_FILE') or ''
if status_file == '' then
  return
end

local write_timer = nil

local station = (os.getenv('SOMA_STATION') or 'SomaFM'):gsub('[%c]', ' '):sub(1, 80)

local function current_output()
  local device = mp.get_property('audio-device') or ''
  if device == '' or device == 'auto' then
    return ''
  end
  return (device:gsub('^pipewire/', ''))
end

local function do_write()
  write_timer = nil
  local data = {
    running = not mp.get_property_bool('idle-active'),
    paused = mp.get_property_bool('pause'),
    muted = mp.get_property_bool('mute'),
    volume = mp.get_property_number('volume') or 70,
    title = tostring(mp.get_property('media-title') or ''):gsub('[%c]', ' '),
    output = current_output(),
    url = tostring(mp.get_property('path') or ''):gsub('[%c]', ' '):sub(1, 200),
    error = '',
    errorDetail = '',
    station = { name = station }
  }
  local ok, json = pcall(utils.format_json, data)
  if not ok then
    return
  end
  local temporary = status_file .. '.new'
  local f = io.open(temporary, 'w')
  if not f then
    return
  end
  f:write(json)
  f:write('\n')
  f:close()
  os.rename(temporary, status_file)
end

local function schedule()
  if write_timer then
    write_timer:kill()
    write_timer = nil
  end
  write_timer = mp.add_timeout(0.25, do_write)
end

mp.observe_property('media-title', 'native', schedule)
mp.observe_property('path', 'string', schedule)
mp.observe_property('pause', 'bool', schedule)
mp.observe_property('mute', 'bool', schedule)
mp.observe_property('volume', 'number', schedule)
mp.observe_property('idle-active', 'bool', schedule)
mp.observe_property('audio-device', 'string', schedule)
mp.register_script_message('somafm-station', function(name)
  station = tostring(name or 'SomaFM'):gsub('[%c]', ' '):sub(1, 80)
  schedule()
end)
schedule()
