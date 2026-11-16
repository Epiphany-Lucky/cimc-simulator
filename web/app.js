/* CIMC Studio — the UI only renders state produced by the simulation engine. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const svg = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const API = location.protocol === 'file:' ? 'http://127.0.0.1:8765' : '';
  let connected = false, state = null, board = null, selectedPin = null, sessionExited = false;
  let activePanel = 'serial', channel = 'ch340', pendingFile = null, busy = false;
  let toastTimer, pollTimer, pollInProgress = false, serialCutoff = -1, diagnosticCutoff = 0;
  let lastWires = '', lastSerial = '', lastDiagnostics = '', lastOled = '';
  let adcPreview = 1.65, adcPending = null, adcSending = false, adcDragging = false, adcDragOrigin = null;
  let schematicPage = 1, schematicReturnFocus = null;
  let firmwareDraft = [], firmwareDraftBoot = null, firmwareDraftSequence = 0, firmwareSetBusy = false, firmwareSetReturnFocus = null;
  const schematicTitles = ['MCU 与排针','板载外设','电源','串口通信'];
  const heldKeys = new Set();
  const preferences = readStorage('cimc.studio.preferences', { labels: false, motion: false, shortcuts: true });
  preferences.autoUpdates ??= true;
  let checkingUpdate = false, lastUpdateAttempt = 0, notifiedVersion = '';

  function readStorage(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) || fallback; } catch { return fallback; } }
  function node(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; }
  function toast(message, error = false) { $('toast').textContent = message; $('toast').classList.add('visible'); $('toast').style.background = error ? '#743d35f5' : ''; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').classList.remove('visible'), error ? 6000 : 3200); }
  function address(value) { if (typeof value === 'string' && value.startsWith('0x')) return value.toUpperCase().replace('0X', '0x'); if (value === undefined || value === null) return '—'; return '0x' + (Number(value) >>> 0).toString(16).padStart(8, '0').toUpperCase(); }
  function bytesLabel(n) { return n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`; }
  function toBase64(bytes) { let s = ''; for (let i = 0; i < bytes.length; i += 8192) s += String.fromCharCode(...bytes.subarray(i, i + 8192)); return btoa(s); }
  function saveFile(name, content, type = 'application/json') { const url = URL.createObjectURL(new Blob([content], { type })); const a = node('a'); a.href = url; a.download = name; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 3000); }
  function stamp() { return new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19); }
  function hasFirmware() { return !!(state?.firmware?.name || state?.firmware?.size); }
  function isRunning() { return state?.status === 'running'; }
  function channelMapping(name) { return state?.board?.serialMappings?.[name] || board?.serialMappings?.[name] || board?.uart_channels?.[name] || null; }

  async function api(path, body) {
    const options = { cache: 'no-store', signal: AbortSignal.timeout(10000) };
    if (body !== undefined) { options.method = 'POST'; options.headers = { 'Content-Type': 'application/json' }; options.body = JSON.stringify(body); }
    const response = await fetch(API + path, options);
    const text = await response.text();
    let data; try { data = JSON.parse(text); } catch { throw new Error('内核返回了无法识别的数据。'); }
    if (!response.ok || data.ok === false || data.error) throw new Error(typeof data.error === 'string' ? data.error : data.message || `请求失败 (${response.status})`);
    return data;
  }

  async function command(action, fields = {}, showError = true) {
    if (!connected) { if (showError) toast('请先启动本地仿真内核。', true); return null; }
    try {
      const result = await api('/api/command', { action, ...fields });
      const next = result.state || (result.status && result.cpu ? result : null);
      if (next) renderState(next);
      else void poll();
      return result;
    } catch (error) { if (showError) toast(error.message, true); return null; }
  }

  async function poll() {
    if (pollInProgress || sessionExited) return;
    pollInProgress = true;
    clearTimeout(pollTimer);
    try {
      const result = await api('/api/state');
      if (sessionExited) return;
      connected = true;
      if (preferences.autoUpdates && !lastUpdateAttempt) void checkUpdates(false);
      $('connection-notice').hidden = true;
      if (!sessionExited) renderState(result.state || result);
    } catch {
      if (sessionExited) return;
      connected = false;
      $('connection-notice').hidden = false;
      $('connection-status').className = 'status-pill';
      $('connection-status').innerHTML = '<i></i>内核未连接';
      $('session-sub').textContent = '等待本地仿真服务';
      $('footer-engine').textContent = '尚未连接 · 不产生模拟输出';
      if (location.protocol === 'file:') $('connection-message').textContent = '请运行启动器，使用浏览器打开 http://127.0.0.1:8765。HTML 文件仍可查看界面。';
      $('oled-live').classList.remove('on');
      updateEnabled();
    } finally {
      pollInProgress = false;
      if (!sessionExited) pollTimer = setTimeout(poll, connected ? (document.hidden ? 700 : 130) : 1600);
    }
  }

  function updateEnabled() {
    $('exit-app-button').hidden = !state?.engine?.desktopSession || sessionExited;
    $('exit-app-button').disabled = !connected || busy;
    document.querySelectorAll('[data-engine]').forEach(b => b.disabled = !connected || busy);
    document.querySelectorAll('[data-firmware]').forEach(b => b.disabled = !connected || !hasFirmware() || busy);
    $('step-button').disabled = !connected || !hasFirmware() || isRunning() || busy;
    $('run-button').disabled = !connected || !hasFirmware() || state?.status === 'faulted' || busy;
    $('serial-send').disabled = !connected || !hasFirmware() || !channelMapping(channel) || busy;
    $('serial-mode').disabled = !connected || busy;
    const adcReady = connected && !!state?.adc;
    $('adc-slider').disabled = !adcReady;
    $('adc-knob').setAttribute('aria-disabled',String(!adcReady));
    $('adc-knob').tabIndex = adcReady ? 0 : -1;
    document.querySelectorAll('[data-channel]').forEach(b => { b.disabled = !channelMapping(b.dataset.channel); b.title = b.disabled ? `${b.dataset.channel.toUpperCase()} 固定映射待 V1 原理图核验` : ''; });
    document.querySelectorAll('.key').forEach(b => b.disabled = !connected || !hasFirmware());
    document.querySelectorAll('.pin').forEach(b => b.disabled = !connected || b.dataset.connectable === 'false');
    updateFirmwareSetControls();
  }

  function renderState(next) {
    if (sessionExited) return;
    state = next;
    const labels = { running: '正在运行', paused: '已暂停', loaded: '固件就绪', ready: '准备就绪', idle: '准备就绪', stopped: '已停止', error: '运行已中止', halted: '运行已中止', faulted: '运行已中止' };
    const status = next.status || 'idle';
    $('connection-status').className = `status-pill ${status === 'running' ? 'running' : ['error','halted','faulted'].includes(status) ? 'error' : 'ready'}`;
    $('connection-status').replaceChildren(node('i'), document.createTextNode(labels[status] || status));
    $('session-sub').textContent = 'GD32F470 · ARM Cortex-M4';
    $('footer-engine').textContent = `ARM 内核${next.engine?.version ? ' ' + next.engine.version : ''} · ${status === 'running' ? '运行中' : '本地连接'}`;
    if (next.board && (!board || next.board.id !== board.id)) setBoard(next.board);
    if (next.board?.pins?.length && !board?.pins?.length) setBoard(next.board);
    const fw = next.firmware || {};
    $('firmware-name').textContent = fw.name || '导入你的固件';
    $('firmware-name').title = fw.name || '';
    const firmwareCount = next.firmwares?.length || (hasFirmware() ? 1 : 0);
    $('firmware-detail').textContent = firmwareCount > 1 ? `${firmwareCount} 个镜像 · 启动 ${address(next.bootAddress)}` : fw.size ? `${bytesLabel(fw.size)} · 点击更换固件` : '选择单文件，或打开“多固件”';
    $('firmware-set-open').textContent = firmwareCount > 1 ? `多固件 · ${firmwareCount}` : '多固件';
    $('firmware-open').title = firmwareCount > 1 ? '导入单文件，将替换当前全部烧录镜像' : '导入单个 HEX 或 BIN';
    $('firmware-set-vtor').textContent = address(next.currentVectorAddress);
    $('firmware-format').textContent = fw.format ? fw.format.toUpperCase() : 'HEX / BIN';
    $('firmware-open').classList.toggle('loaded', hasFirmware());
    $('firmware-meta').hidden = !hasFirmware();
    $('entry-address').textContent = address(fw.entry);
    const run = $('run-button');
    run.classList.toggle('running', isRunning());
    run.querySelector('use').setAttribute('href', isRunning() ? '#i-pause' : '#i-play');
    run.querySelector('span').textContent = isRunning() ? '暂停' : '运行';
    $('cpu-pc').textContent = address(next.cpu?.pc);
    $('cpu-instructions').textContent = Number(next.cpu?.instructions || 0).toLocaleString('en-US');
    renderLeds(next.leds || []);
    (next.keys || []).forEach((pressed, i) => { const key = $('keys').children[i]; if (key) key.classList.toggle('pressed', !!(typeof pressed === 'object' ? pressed.pressed : pressed)); });
    renderOled(next.oled);
    renderAdc(next.adc);
    renderFlash(next.flash);
    if (['rs485','rs232'].includes(next.serialMode)) $('serial-mode').value = next.serialMode;
    renderWires(next.wires || []);
    renderSerial();
    renderDiagnostics();
    updateEnabled();
    updateChannelNote();
  }

  function updateChannelNote() {
    const mapping = channelMapping(channel);
    $('serial-mode-label').textContent = typeof mapping === 'string' ? mapping : mapping?.uart || '待核验';
    const message = channel.startsWith('rs') ? `H6 当前选择 ${(state?.serialMode || 'rs485').toUpperCase()}。RS232 / RS485 共用 USART1；通过右侧接口选择切换，页签只切换终端视图。` : channel === 'ch340' ? 'H7 · CH340 固定连接 USART0，无需手动接线。' : 'CN1 · USART2：PB10 TX / PB11 RX，TTL 调试通道。';
    $('channel-note').textContent = message;
    $('channel-note').hidden = !message;
  }

  function setBoard(profile) {
    board = profile;
    const photo = $('board-image');
    if (profile.image) {
      photo.onload = () => { photo.hidden = false; $('board-placeholder').hidden = true; };
      photo.onerror = () => { photo.hidden = true; $('board-placeholder').hidden = false; $('board-placeholder').querySelector('span').textContent = '板卡图片暂未载入'; };
      photo.src = profile.image;
    }
    if (profile.verified === false) {
      $('board-info-button').firstChild.textContent = 'V1 原理图 · 接线视图';
      $('board-info-button').title = '点击查看原理图证据与仿真范围';
    }
    const viewBox = profile.viewBox || [0, 0, 1000, 650];
    $('wire-layer').setAttribute('viewBox', viewBox.join(' '));
    $('board-visual').style.aspectRatio = `${viewBox[2]}/${viewBox[3]}`;
    $('pin-layer').replaceChildren();
    for (const pin of profile.pins || []) {
      const b = node('button', 'pin');
      b.style.left = `${(pin.x - viewBox[0]) / viewBox[2] * 100}%`;
      b.style.top = `${(pin.y - viewBox[1]) / viewBox[3] * 100}%`;
      b.dataset.pin = pin.id; b.dataset.label = pin.label || pin.id;
      b.dataset.connectable = pin.connectable === false || pin.locked ? 'false' : 'true';
      b.dataset.locked = pin.lockedReason ? 'true' : 'false';
      b.setAttribute('aria-label', `排针 ${pin.group || ''} ${pin.label || pin.id}${pin.net ? '，网络 ' + pin.net : ''}`);
      b.title = `${pin.group || ''} · ${pin.label || pin.id}${pin.net ? ' → ' + pin.net : ''}${pin.lockedReason ? '（' + pin.lockedReason + '）' : pin.connectable === false ? '（不可连接）' : ''}`;
      b.addEventListener('click', () => choosePin(pin));
      $('pin-layer').append(b);
    }
    buildHardwareControls(profile.keys?.length || 6, profile.leds?.length || 6);
    lastWires = '';
    renderWires(state?.wires || []);
    updateEnabled();
  }

  async function choosePin(pin) {
    if (!connected || pin.connectable === false || pin.locked) return;
    if (!selectedPin) {
      selectedPin = pin.id;
      document.querySelectorAll('.pin').forEach(b => b.classList.toggle('selected', b.dataset.pin === selectedPin));
      $('wiring-hint').classList.add('selecting');
      $('wiring-hint').lastElementChild.textContent = `${pin.label || pin.id} 已选中 · 点击另一端点，Esc 取消`;
      return;
    }
    if (selectedPin === pin.id) { clearPinSelection(); return; }
    const from = selectedPin;
    clearPinSelection();
    const colors = ['#43a5ff','#f3a346','#ba8ce5','#51c69e','#e6849e','#68bec9'];
    const result = await command('wire_add', { from, to: pin.id, color: colors[(state?.wires?.length || 0) % colors.length] });
    if (result) toast(`已连接 ${from} → ${pin.id}`);
  }

  function clearPinSelection() {
    selectedPin = null;
    document.querySelectorAll('.pin.selected').forEach(b => b.classList.remove('selected'));
    $('wiring-hint').classList.remove('selecting');
    $('wiring-hint').lastElementChild.textContent = '选择空闲 GPIO 与 LED / KEY 排针，添加跳线';
  }

  function renderWires(wires) {
    const managed = state?.managedWires || [];
    const fixed = board?.fixedVisualWires || [];
    const signature = JSON.stringify([wires,managed,fixed]) + (board?.id || '');
    if (signature === lastWires) return;
    lastWires = signature;
    $('wire-count').textContent = wires.length;
    $('wire-layer').replaceChildren();
    $('wire-list').replaceChildren();
    const pins = new Map((board?.pins || []).map(p => [p.id, p]));
    [...fixed.map(w=>({...w,locked:true,fixedVisual:true})),...managed.map(w=>({...w,locked:true})),...wires].forEach((w, index) => {
      const from = w.from ?? w.a ?? w.fromPin, to = w.to ?? w.b ?? w.toPin;
      const a = pins.get(from), b = pins.get(to), color = /^#[0-9a-f]{3,8}$/i.test(w.color || '') ? w.color : '#43a5ff';
      if (a && b) {
        const height = Math.min(125, Math.max(35, Math.abs(b.x - a.x) * .22 + Math.abs(b.y - a.y) * .12));
        const points = w.fixedVisual && Array.isArray(w.points) && w.points.length > 1 && w.points.every(p=>Array.isArray(p) && p.length === 2 && p.every(Number.isFinite)) ? w.points : null;
        const path = points ? points.map((p,i)=>`${i ? 'L' : 'M'} ${p[0]} ${p[1]}`).join(' ') : `M ${a.x} ${a.y} C ${a.x} ${a.y-height}, ${b.x} ${b.y-height}, ${b.x} ${b.y}`;
        if (!w.fixedVisual) {
          const hit = document.createElementNS('http://www.w3.org/2000/svg', 'path');
          hit.setAttribute('d', path); hit.setAttribute('class', 'wire-hit');
          hit.addEventListener('click', () => { activatePanel('wires'); $('console-card').scrollIntoView({ behavior: 'smooth', block: 'nearest' }); });
          $('wire-layer').append(hit);
        }
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        line.setAttribute('d', path); line.setAttribute('stroke', color); line.setAttribute('stroke-width', '4');
        if (w.fixedVisual) {
          line.setAttribute('class','fixed-board-wire'); line.dataset.wireId = w.id; line.dataset.from = from; line.dataset.to = to;
          line.setAttribute('aria-label',`${w.label || '原板固定线'}：${from} 至 ${to}`);
        } else if (w.locked) { line.setAttribute('stroke-width','2.5'); line.setAttribute('stroke-dasharray','5 4'); }
        $('wire-layer').append(line);
      }
      const row = node('div', w.fixedVisual ? 'wire-row fixed-wire-row' : 'wire-row');
      if (w.fixedVisual) row.dataset.wireId = w.id;
      const swatch = node('span', 'wire-swatch'); swatch.style.background = color;
      row.append(swatch, node('code', '', from), node('span', 'wire-arrow', '→'), node('code', '', to));
      if (w.demo || w.source === 'demo') row.append(node('small', '', '示例跳线'));
      if (w.fixedVisual) row.append(node('small','fixed-wire-label',w.label || '原板固定线'));
      else if (w.locked) row.append(node('small','managed-wire-label','系统连接 · 已锁定'));
      else {
        const del = node('button', 'icon-button'); del.innerHTML = svg('trash'); del.title = '删除这条用户跳线'; del.setAttribute('aria-label', `删除跳线 ${from} 至 ${to}`);
        del.addEventListener('click', async () => { if (await command('wire_remove', { id: w.id ?? index - fixed.length - managed.length })) toast('已删除用户跳线，原板固定连线保持不变。'); });
        row.append(del);
      }
      $('wire-list').append(row);
    });
    if (!wires.length) $('wire-list').append(empty('wire', '还没有添加用户跳线', '选择未占用 GPIO 与 LED / KEY 排针，添加连接。'));
  }

  function buildHardwareControls(keyCount, ledCount) {
    if ($('keys').children.length !== keyCount) {
      $('keys').replaceChildren();
      for (let i = 0; i < keyCount; i++) {
        const b = node('button', 'key', String(i + 1)); b.dataset.index = i;
        b.title = `KEY${i + 1} · 按下与松开`; b.setAttribute('aria-label', `KEY${i+1}`);
        b.addEventListener('pointerdown', e => { if (b.disabled) return; e.preventDefault(); b.setPointerCapture(e.pointerId); pressKey(i, true); });
        b.addEventListener('pointerup', () => pressKey(i, false));
        b.addEventListener('pointercancel', () => pressKey(i, false));
        b.addEventListener('lostpointercapture', () => pressKey(i, false));
        b.addEventListener('keydown', e => { if ([' ', 'Enter'].includes(e.key)) { e.preventDefault(); if (!e.repeat) pressKey(i, true); } });
        b.addEventListener('keyup', e => { if ([' ', 'Enter'].includes(e.key)) { e.preventDefault(); pressKey(i, false); } });
        b.addEventListener('blur', () => pressKey(i, false));
        $('keys').append(b);
      }
    }
    if ($('leds').children.length !== ledCount) {
      $('leds').replaceChildren();
      for (let i = 0; i < ledCount; i++) { const led = node('div','led-item'); const light = node('i','led-light'); light.setAttribute('role','img'); light.setAttribute('aria-label',`LED${i+1} 熄灭`); led.append(light,node('span','',String(i+1))); $('leds').append(led); }
    }
  }

  async function pressKey(index, pressed) {
    if (pressed && (!connected || !hasFirmware())) return;
    if (pressed === heldKeys.has(index)) return;
    if (pressed) heldKeys.add(index); else heldKeys.delete(index);
    const result = await command('key', { index, pressed }, pressed);
    if (!result && pressed) heldKeys.delete(index);
  }

  function releaseKeys() { for (const index of [...heldKeys]) void pressKey(index, false); }
  function renderLeds(leds) { leds.forEach((entry, i) => { const on = typeof entry === 'object' ? !!(entry.on ?? entry.value) : !!entry; const n = $('leds').children[i]?.firstChild; if (n) { n.classList.toggle('on', on); n.setAttribute('aria-label',`LED${i+1} ${on ? '点亮' : '熄灭'}`); } }); }
  function renderOled(oled) {
    if (!oled) return;
    const width = Math.min(256, Math.max(1, oled.width || 128)), height = Math.min(128, Math.max(1, oled.height || 32));
    let pixels = oled.pixels || [];
    if (typeof pixels === 'string') { try { pixels = [...atob(pixels)].map(c => c.charCodeAt(0)); } catch { pixels = []; } }
    const enabled = oled.enabled ?? oled.on ?? true;
    const signature = `${width}x${height}:${enabled}:${Array.isArray(pixels) ? pixels.join('') : ''}`;
    $('oled-live').classList.toggle('on', isRunning());
    $('oled-state').textContent = hasFirmware() ? (!enabled ? '屏幕已关闭' : isRunning() ? '接收固件输出' : '保留最后一帧') : '等待固件输出';
    if (signature === lastOled) return;
    lastOled = signature;
    const canvas = $('oled-canvas'); canvas.width = width; canvas.height = height;
    const ctx = canvas.getContext('2d'); const bitmap = ctx.createImageData(width, height);
    for (let i = 0; i < width * height; i++) { const on = enabled && !!pixels[i]; bitmap.data[i*4] = on ? 182 : 11; bitmap.data[i*4+1] = on ? 232 : 17; bitmap.data[i*4+2] = on ? 251 : 25; bitmap.data[i*4+3] = 255; }
    ctx.putImageData(bitmap, 0, 0); $('oled-size').textContent = `${width} × ${height}`;
  }

  function showAdcInput(voltage) {
    const limit = Number(state?.adc?.referenceVoltage) || 3.3;
    const value = Math.max(0,Math.min(limit,Number(voltage) || 0));
    adcPreview = value;
    $('adc-voltage').textContent = `${value.toFixed(3)} V`;
    $('adc-slider').max = String(limit);
    $('adc-slider').value = String(value);
    $('adc-knob').setAttribute('aria-valuemax',String(limit));
    $('adc-knob').setAttribute('aria-valuenow',value.toFixed(3));
    $('adc-knob').setAttribute('aria-valuetext',`${value.toFixed(3)} V`);
    $('adc-needle').style.transform = `rotate(${-135 + value / limit * 270}deg)`;
  }

  function renderAdc(adc) {
    if (!adc) return;
    if (!adcDragging && !adcSending && adcPending === null) showAdcInput(adc.voltage);
    const sampled = Number(adc.sampleCount) > 0 && adc.value !== null && adc.value !== undefined;
    $('adc-sample').textContent = sampled ? `采样 ${adc.value} / ${2 ** (adc.bits || 12) - 1}` : '待固件采样';
    $('adc-sample').title = sampled ? `固件最近一次 ADC 转换结果；已转换 ${adc.sampleCount} 次` : '输入电压已设置，等待 MCU 固件发起 ADC 转换';
  }

  async function sendAdcInput() {
    if (adcSending || adcPending === null) return;
    adcSending = true;
    try {
      while (adcPending !== null) {
        const voltage = adcPending;
        adcPending = null;
        if (!await command('adc_voltage',{voltage})) { adcPending = null; break; }
      }
    } finally {
      adcSending = false;
      if (!adcDragging && state?.adc) renderAdc(state.adc);
    }
  }

  function setAdcInput(voltage) {
    if (!connected || !state?.adc) return;
    showAdcInput(Math.round(voltage * 1000) / 1000);
    adcPending = adcPreview;
    void sendAdcInput();
  }

  function renderFlash(flash) {
    if (!flash) return;
    const command = flash.lastCommand;
    $('flash-command').textContent = typeof command === 'number' ? `CMD 0x${command.toString(16).padStart(2,'0').toUpperCase()}` : command || '—';
    const status = flash.status;
    $('flash-state').textContent = command === null || command === undefined ? '等待固件访问' : typeof status === 'number' ? (status & 1 ? '操作中' : status & 2 ? '写使能' : '就绪') : status === 'busy' ? '操作中' : status === 'deep-power-down' ? '深度休眠' : flash.writeEnabled ? '写使能' : '就绪';
    $('flash-state').title = typeof status === 'number' ? `状态寄存器 0x${status.toString(16).padStart(2,'0').toUpperCase()}` : String(status || '');
    $('flash-reads').textContent = `${Number(flash.readCount || 0).toLocaleString('en-US')} B`;
    $('flash-writes').textContent = `${Number(flash.writeCount || 0).toLocaleString('en-US')} 次`;
    $('flash-erases').textContent = `${Number(flash.eraseCount || 0).toLocaleString('en-US')} 次`;
  }

  function empty(icon, title, subtitle) { const e = node('div','empty-state'); const i = node('span','empty-icon'); i.innerHTML = svg(icon); e.append(i,node('p','',title),node('span','',subtitle)); return e; }
  function logTime(value) { if (!value) return '—'; if (typeof value === 'string' && /^\d\d:\d\d/.test(value)) return value; const date = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value); return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleTimeString('en-GB', { hour12:false }); }
  function serialEntries() { return (state?.serial || []).filter((entry,index) => (entry.channel || 'ch340').toLowerCase() === channel && (Number(entry.id) || index) > serialCutoff); }
  function renderSerial(force = false) {
    const entries = serialEntries().slice(-350);
    const signature = JSON.stringify(entries);
    if (!force && lastSerial === signature) return;
    lastSerial = signature;
    const terminal = $('terminal'); const oldTop = terminal.scrollTop;
    terminal.replaceChildren();
    if (!entries.length) terminal.append(empty('terminal','等待第一条消息','运行固件后，在这里与开发板对话。'));
    entries.forEach(entry => {
      const direction = (entry.direction || 'rx').toLowerCase();
      const row = node('div','log-line');
      const content = $('serial-format').value === 'hex' ? entry.hex || entry.text || '' : entry.text ?? entry.hex ?? '';
      row.append(node('span','log-time',logTime(entry.time)),node('span',`log-direction ${direction === 'tx' ? 'tx' : ''}`,direction.toUpperCase()),node('span','log-content',content));
      terminal.append(row);
    });
    terminal.scrollTop = $('auto-scroll').checked ? terminal.scrollHeight : oldTop;
  }

  function renderDiagnostics(force = false) {
    const all = state?.diagnostics || [], entries = all.slice(diagnosticCutoff).slice(-100);
    $('diagnostic-count').textContent = entries.length;
    $('diagnostic-count').classList.toggle('alert', entries.some(x => ['warning','error','warn'].includes(x.level)));
    const signature = JSON.stringify(entries);
    if (!force && signature === lastDiagnostics) return;
    lastDiagnostics = signature;
    $('diagnostic-list').replaceChildren();
    if (!entries.length) $('diagnostic-list').append(empty('check','暂时没有运行提示','有新的诊断信息时，会在这里显示。'));
    entries.forEach(entry => {
      const row = node('div','diagnostic-row'); const level = entry.level === 'warn' ? 'warning' : entry.level || 'info';
      row.append(node('span',`diagnostic-level ${level}`,level.toUpperCase()),node('div','diagnostic-message',entry.message || String(entry)));
      $('diagnostic-list').append(row);
    });
  }

  function activatePanel(name) {
    activePanel = name;
    document.querySelectorAll('[data-panel]').forEach(b => { const active = b.dataset.panel === name; b.classList.toggle('active',active); b.setAttribute('aria-selected',String(active)); });
    document.querySelectorAll('.panel').forEach(panel => { const active = panel.id === `panel-${name}`; panel.hidden = !active; panel.classList.toggle('active',active); });
  }

  async function loadDemo() {
    busy = true; updateEnabled();
    const result = await command('demo');
    busy = false; serialCutoff = -1; diagnosticCutoff = 0; updateEnabled();
    if (result) toast(`示例固件与 ${state?.wires?.length || 0} 条 LED/KEY 跳线已载入，板载连接保持固定。点击运行。`);
  }

  function setFirmwareDraftError(message = '') {
    $('firmware-set-error').textContent = message;
    $('firmware-set-error').hidden = !message;
  }

  function updateFirmwareSetControls() {
    const custom = $('firmware-set-custom').checked;
    $('firmware-set-apply').disabled = firmwareSetBusy || !connected || !firmwareDraft.length;
    $('firmware-set-apply').textContent = firmwareSetBusy ? '正在烧录…' : '一次烧录';
    $('firmware-set-add').disabled = firmwareSetBusy;
    $('firmware-set-custom').disabled = firmwareSetBusy;
    $('firmware-set-boot-address').disabled = firmwareSetBusy || !custom;
    document.querySelectorAll('#firmware-set-dialog [data-close], #firmware-set-list button, #firmware-set-list input').forEach(control=>{
      control.disabled = firmwareSetBusy || (control.type === 'radio' && custom);
    });
    $('firmware-set-count').textContent = `${firmwareDraft.length} 个镜像`;
    const selected = firmwareDraft.find(entry=>entry.key === firmwareDraftBoot);
    const summary = custom ? `从 ${$('firmware-set-boot-address').value || '自定义地址'} 启动` : selected ? `从 ${selected.name} 启动` : '添加固件后选择启动项';
    $('firmware-set-start-summary').textContent = summary;
    $('firmware-set-start-summary').title = summary;
  }

  function renderFirmwareDraft() {
    const list = $('firmware-set-list');
    list.replaceChildren();
    firmwareDraft.forEach(entry=>{
      const row = node('div','firmware-set-row'); row.dataset.key = entry.key;
      row.classList.toggle('boot-selected',entry.key === firmwareDraftBoot && !$('firmware-set-custom').checked);
      const start = node('label','firmware-boot-choice');
      const radio = node('input'); radio.type = 'radio'; radio.name = 'firmware-boot'; radio.value = entry.key; radio.checked = entry.key === firmwareDraftBoot;
      radio.setAttribute('aria-label',`从 ${entry.name} 启动`);
      radio.addEventListener('change',()=>{
        firmwareDraftBoot=entry.key;setFirmwareDraftError();
        list.querySelectorAll('.firmware-set-row').forEach(item=>item.classList.toggle('boot-selected',item.dataset.key === firmwareDraftBoot));
        updateFirmwareSetControls();
      });
      start.append(radio,node('span','','启动'));
      const identity = node('div','firmware-set-identity');
      const filename = node('strong','',entry.name); filename.title = entry.name;
      identity.append(filename,node('span','',`${entry.format.toUpperCase()} · ${bytesLabel(entry.size)} · ${entry.id ? '已烧录' : '新增'}`));
      const location = node('div','firmware-set-location');
      if (entry.format === 'bin' && !entry.id) {
        const label = node('label','','装载地址'); label.htmlFor = `firmware-address-${entry.key}`;
        const input = node('input','firmware-image-address'); input.id = label.htmlFor; input.value = entry.address; input.spellcheck = false;
        input.setAttribute('aria-label',`${entry.name} BIN 装载地址`);
        input.addEventListener('input',()=>{entry.address=input.value;setFirmwareDraftError();updateFirmwareSetControls();});
        location.append(label,input);
      } else {
        location.append(node('span','',entry.format === 'hex' && !entry.id ? 'HEX 内置地址' : '装载地址'),node('code','',entry.address ? address(entry.address) : '由文件记录决定'));
        if (entry.id && entry.format === 'bin') location.append(node('small','','重选文件可调整地址'));
      }
      const remove = node('button','icon-button firmware-remove'); remove.type = 'button'; remove.innerHTML = svg('trash'); remove.title = '从待烧录列表移除'; remove.setAttribute('aria-label',`移除 ${entry.name}`);
      remove.addEventListener('click',()=>{
        const index = firmwareDraft.findIndex(item=>item.key === entry.key);
        firmwareDraft = firmwareDraft.filter(item=>item.key !== entry.key);
        if (firmwareDraftBoot === entry.key) firmwareDraftBoot = firmwareDraft[0]?.key || null;
        setFirmwareDraftError(); renderFirmwareDraft();
        (list.children[Math.min(index,firmwareDraft.length-1)]?.querySelector('.firmware-remove') || $('firmware-set-add')).focus();
      });
      row.append(start,identity,location,remove); list.append(row);
    });
    if (!firmwareDraft.length) list.append(empty('file','添加你的固件','支持多个 HEX / BIN；各 BIN 使用自己的链接地址。'));
    updateFirmwareSetControls();
  }

  function openFirmwareSet() {
    if ($('firmware-set-dialog').open) return;
    firmwareSetReturnFocus = document.activeElement;
    firmwareDraft = (state?.firmwares || []).map(item=>({id:item.id,key:String(++firmwareDraftSequence),name:item.name,format:String(item.format).toLowerCase(),size:item.size,address:item.address}));
    firmwareDraftBoot = (firmwareDraft.find(item=>item.id === state?.firmware?.id) || firmwareDraft[0])?.key || null;
    const selected = firmwareDraft.find(item=>item.key === firmwareDraftBoot);
    const custom = state?.bootAddress != null && selected && Number(state.bootAddress) !== Number(selected.address);
    $('firmware-set-custom').checked = !!custom;
    $('firmware-set-boot-address').value = address(state?.bootAddress ?? '0x08000000');
    $('firmware-set-advanced').open = !!custom;
    setFirmwareDraftError(); renderFirmwareDraft(); releaseKeys();
    $('firmware-set-dialog').showModal(); document.body.classList.add('firmware-set-open');
    $('firmware-set-add').focus();
  }

  function addFirmwareFiles(files) {
    if (firmwareSetBusy) return;
    const additions = Array.from(files || []);
    if (!additions.length) return;
    const invalid = additions.find(file=>!(/\.(hex|bin)$/i.test(file.name)) || file.size > 4 * 1024 * 1024 || !file.size);
    if (invalid) { setFirmwareDraftError(`${invalid.name}：请选择非空 HEX / BIN，单文件不超过 4 MiB。`); return; }
    firmwareDraft.push(...additions.map(file=>({file,key:String(++firmwareDraftSequence),name:file.name,format:file.name.toLowerCase().endsWith('.bin') ? 'bin' : 'hex',size:file.size,address:file.name.toLowerCase().endsWith('.bin') ? '0x08000000' : null})));
    if (!firmwareDraftBoot) firmwareDraftBoot = firmwareDraft[0].key;
    setFirmwareDraftError(); renderFirmwareDraft();
  }

  $('firmware-set-open').addEventListener('click',openFirmwareSet);
  $('firmware-set-add').addEventListener('click',()=>$('firmware-set-files').click());
  $('firmware-set-files').addEventListener('change',e=>{addFirmwareFiles(e.target.files);e.target.value='';});
  $('firmware-set-custom').addEventListener('change',()=>{setFirmwareDraftError();renderFirmwareDraft();});
  $('firmware-set-boot-address').addEventListener('input',()=>{setFirmwareDraftError();updateFirmwareSetControls();});
  $('firmware-set-dialog').addEventListener('cancel',e=>{if(firmwareSetBusy)e.preventDefault();});
  $('firmware-set-dialog').addEventListener('close',()=>{
    document.body.classList.remove('firmware-set-open'); firmwareDraft=[]; firmwareDraftBoot=null;
    firmwareSetReturnFocus?.focus({preventScroll:true});
  });
  $('firmware-set-form').addEventListener('submit',async event=>{
    event.preventDefault();
    if (firmwareSetBusy || !firmwareDraft.length || !connected) return;
    const validAddress = value=>/^(0x[0-9a-f]+|\d+)$/i.test(value.trim()) && Number.isSafeInteger(Number(value)) && Number(value) <= 0xFFFFFFFF;
    const invalid = firmwareDraft.find(item=>!item.id && item.format === 'bin' && !validAddress(item.address));
    if (invalid) { setFirmwareDraftError(`${invalid.name}：请输入有效 BIN 装载地址，例如 0x08010000。`); return; }
    const custom = $('firmware-set-custom').checked, bootAddress = $('firmware-set-boot-address').value.trim();
    if (custom && !validAddress(bootAddress)) { setFirmwareDraftError('请输入有效的启动向量地址，例如 0x08000000。'); return; }
    if (firmwareDraft.reduce((size,item)=>size + (item.file ? 4 * Math.ceil(item.file.size/3) : 0),0) > 16 * 1024 * 1024) { setFirmwareDraftError('新增文件编码后超过单次 16 MiB 请求限制，请减少文件体积。'); return; }
    firmwareSetBusy=true;busy=true;setFirmwareDraftError();updateEnabled();
    try {
      const images = await Promise.all(firmwareDraft.map(async item=>item.id ? {id:item.id} : {filename:item.name,data:toBase64(new Uint8Array(await item.file.arrayBuffer())),...(item.format === 'bin' ? {address:item.address.trim()} : {})}));
      const fields = custom ? {bootAddress} : {bootIndex:Math.max(0,firmwareDraft.findIndex(item=>item.key === firmwareDraftBoot))};
      const payload = {action:'load_set',images,...fields};
      if (new TextEncoder().encode(JSON.stringify(payload)).length > 16 * 1024 * 1024) throw new Error('固件集合超过单次 16 MiB 请求限制，请减少文件体积。');
      const result = await api('/api/command',payload);
      const next = result.state || result;
      if (next.status && next.cpu) renderState(next);
      else await poll();
      serialCutoff=-1;diagnosticCutoff=0;
      $('firmware-set-dialog').close();
      toast(`已烧录 ${images.length} 个镜像，点击“运行”从所选向量启动。`);
    } catch(error) { setFirmwareDraftError(error.message); }
    finally {firmwareSetBusy=false;busy=false;updateEnabled();}
  });

  function prepareFile(file) {
    if (!file) return;
    if (!/\.(hex|bin)$/i.test(file.name)) { toast('请选择 .hex 或 .bin 固件文件。',true); return; }
    if (file.size > 4 * 1024 * 1024) { toast('固件文件超过 4 MB，请检查选择的文件。',true); return; }
    pendingFile = file;
    $('import-filename').textContent = file.name;
    $('import-filesize').textContent = bytesLabel(file.size);
    $('address-field').hidden = !/\.bin$/i.test(file.name);
    $('import-description').textContent = (/\.bin$/i.test(file.name) ? 'BIN 文件不包含装载地址，请确认链接配置。' : 'HEX 文件包含装载地址，内核将检查校验和与地址范围。') + (state?.firmwares?.length > 1 ? '此次导入将替换当前全部镜像；一起烧录请使用“多固件”。' : '');
    $('import-dialog').showModal();
  }

  $('import-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (!pendingFile) return;
    const file = pendingFile;
    const loadAddress = $('bin-address').value.trim();
    if (/\.bin$/i.test(file.name) && !/^(0x[0-9a-f]+|\d+)$/i.test(loadAddress)) { toast('请输入有效的装载地址，例如 0x08000000。',true); return; }
    $('import-confirm').disabled = true;
    try {
      const data = toBase64(new Uint8Array(await file.arrayBuffer()));
      const result = await command('load', { filename:file.name, data, address:loadAddress });
      if (result) { $('import-dialog').close(); pendingFile = null; serialCutoff = -1; diagnosticCutoff = 0; toast('固件已载入，等待运行。'); }
    } catch(error) { toast(error.message,true); }
    finally { $('import-confirm').disabled = false; $('firmware-file').value = ''; }
  });

  $('serial-form').addEventListener('submit', async event => {
    event.preventDefault(); const value = $('serial-input').value;
    if (!channelMapping(channel)) { toast('此通道固定映射待 V1 原理图核验，暂时无法发送。',true); return; }
    if (!value) { $('serial-input').focus(); return; }
    let bytes;
    if ($('serial-format').value === 'hex') {
      const compact = value.replace(/\s/g,'');
      if (!/^(?:[0-9a-f]{2})+$/i.test(compact)) { toast('HEX 格式应为完整字节，例如 48 65 6C 6C 6F。',true); return; }
      bytes = Uint8Array.from(compact.match(/../g), x => parseInt(x,16));
    } else bytes = new TextEncoder().encode(value + ($('serial-newline').checked ? '\r\n' : ''));
    if (bytes.length > 65536) { toast('单次消息不能超过 64 KB。',true); return; }
    const result = await command('serial', { channel, data:toBase64(bytes) });
    if (result) { $('serial-input').value = ''; $('serial-input').focus(); }
  });

  $('firmware-open').addEventListener('click', () => $('firmware-file').click());
  $('firmware-file').addEventListener('change',e => prepareFile(e.target.files[0]));
  $('run-button').addEventListener('click', () => command(isRunning() ? 'pause' : 'run'));
  $('reset-button').addEventListener('click', async () => { releaseKeys(); if (await command('reset')) { serialCutoff = -1; diagnosticCutoff = 0; toast('固件已复位，用户跳线保持不变。'); } });
  $('step-button').addEventListener('click', () => command('step'));
  $('demo-button').addEventListener('click',loadDemo);
  $('quick-demo').addEventListener('click',loadDemo);
  $('retry-button').addEventListener('click',() => { clearTimeout(pollTimer); void poll(); });
  $('pin-toggle').addEventListener('click',() => { const on = $('pin-toggle').getAttribute('aria-pressed') !== 'true'; $('pin-toggle').setAttribute('aria-pressed',String(on)); $('pin-toggle').classList.toggle('selected',on); $('board-visual').classList.toggle('hide-pins',!on); if (!on) clearPinSelection(); });
  $('board-expand').addEventListener('click',() => { $('board-card').classList.toggle('expanded'); $('board-expand').setAttribute('aria-label',$('board-card').classList.contains('expanded') ? '还原开发板大小' : '放大开发板'); });
  $('oled-capture').addEventListener('click',() => { const a = node('a'); a.href = $('oled-canvas').toDataURL('image/png'); a.download = `oled-${stamp()}.png`; a.click(); toast('OLED 像素截图已保存。'); });
  document.querySelectorAll('[data-panel]').forEach(b => b.addEventListener('click',() => activatePanel(b.dataset.panel)));
  document.querySelectorAll('[data-channel]').forEach(b => b.addEventListener('click',() => { channel = b.dataset.channel; document.querySelectorAll('[data-channel]').forEach(x => x.classList.toggle('active',x === b)); updateEnabled(); updateChannelNote(); renderSerial(true); }));
  $('serial-mode').addEventListener('change',async e => {
    const mode = e.target.value;
    if (await command('serial_mode',{mode})) toast(`H6 已选择 ${mode.toUpperCase()}，板载固定连线保持不变。`);
    else e.target.value = state?.serialMode || 'rs485';
  });
  $('adc-slider').addEventListener('input',e=>setAdcInput(Number(e.target.value)));
  $('adc-knob').addEventListener('pointerdown',e=>{
    if ($('adc-knob').getAttribute('aria-disabled') === 'true') return;
    e.preventDefault(); $('adc-knob').focus(); $('adc-knob').setPointerCapture(e.pointerId);
    adcDragging = true; adcDragOrigin = {x:e.clientX,y:e.clientY,voltage:adcPreview};
  });
  $('adc-knob').addEventListener('pointermove',e=>{
    if (adcDragging && adcDragOrigin) setAdcInput(adcDragOrigin.voltage + ((e.clientX-adcDragOrigin.x) - (e.clientY-adcDragOrigin.y)) * .012);
  });
  function endAdcDrag() { adcDragging = false; adcDragOrigin = null; if (state?.adc) renderAdc(state.adc); }
  for (const event of ['pointerup','pointercancel','lostpointercapture']) $('adc-knob').addEventListener(event,endAdcDrag);
  $('adc-knob').addEventListener('keydown',e=>{
    if ($('adc-knob').getAttribute('aria-disabled') === 'true') return;
    const max = Number(state?.adc?.referenceVoltage) || 3.3;
    const values = {ArrowUp:adcPreview+.01,ArrowRight:adcPreview+.01,ArrowDown:adcPreview-.01,ArrowLeft:adcPreview-.01,PageUp:adcPreview+.1,PageDown:adcPreview-.1,Home:0,End:max};
    if (e.key in values) { e.preventDefault(); setAdcInput(values[e.key]); }
  });
  $('serial-format').addEventListener('change',() => { $('serial-input').placeholder = $('serial-format').value === 'hex' ? '输入十六进制字节，例如 48 65 6C 6C 6F…' : '输入消息，按 Enter 发送…'; renderSerial(true); });

  document.querySelectorAll('[data-nav]').forEach(b => b.addEventListener('click',() => { document.querySelectorAll('[data-nav]').forEach(x => x.classList.toggle('active',x === b)); const target = b.dataset.nav; if (target === 'workbench') $('workbench').scrollIntoView({behavior:'smooth'}); else { activatePanel(target); $('console-card').scrollIntoView({behavior:'smooth',block:'start'}); } }));
  document.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click',() => b.closest('dialog')?.close()));
  document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('click',e => { if (e.target !== dialog || (dialog.id === 'firmware-set-dialog' && firmwareSetBusy)) return; const r = dialog.getBoundingClientRect(); if (e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom) dialog.close(); }));
  $('help-button').addEventListener('click',() => $('help-dialog').showModal());
  $('exit-app-button').addEventListener('click',async () => {
    if (!state?.engine?.desktopSession || !connected) return;
    busy = true; updateEnabled();
    try {
      await api('/api/session/quit',{instanceId:state.engine.instanceId});
      sessionExited = true; connected = false; clearTimeout(pollTimer);
      $('connection-status').className = 'status-pill';
      $('connection-status').replaceChildren(node('i'),document.createTextNode('应用已退出'));
      $('session-sub').textContent = '可以关闭此页面';
      $('footer-engine').textContent = '本次仿真会话已结束';
      $('oled-live').classList.remove('on');
      $('connection-notice').hidden = false;
      $('connection-notice').querySelector('strong').textContent = '应用已退出';
      $('connection-message').textContent = '可关闭此页面；需要继续时，从应用菜单重新启动 CIMC Studio。';
      $('retry-button').hidden = true;
    } catch(error) { toast(error.message,true); }
    finally { busy = false; updateEnabled(); }
  });
  $('settings-button').addEventListener('click',() => $('settings-dialog').showModal());

  function applySchematicZoom() {
    const image = $('schematic-image'), zoom = $('schematic-zoom').value;
    image.style.width = zoom === 'fit' ? '100%' : `${(image.naturalWidth || 3200) * Number(zoom) / 100}px`;
  }
  function showSchematicPage(page) {
    schematicPage = Math.max(1,Math.min(schematicTitles.length,Number(page) || 1));
    $('schematic-page-select').value = String(schematicPage);
    $('schematic-page-count').textContent = `${schematicPage} / ${schematicTitles.length}`;
    $('schematic-prev').disabled = schematicPage === 1;
    $('schematic-next').disabled = schematicPage === schematicTitles.length;
    const image = $('schematic-image');
    image.hidden = true;
    image.alt = `GD32F470 V1.0 原理图，第 ${schematicPage} 页：${schematicTitles[schematicPage-1]}`;
    $('schematic-loading').textContent = '正在载入原理图…';
    $('schematic-loading').hidden = false;
    image.src = `assets/schematics/v1-page-${schematicPage}.png`;
    $('schematic-viewport').scrollTo({top:0,left:0,behavior:'instant'});
  }
  $('schematic-image').addEventListener('load',()=>{applySchematicZoom();$('schematic-image').hidden=false;$('schematic-loading').hidden=true;});
  $('schematic-image').addEventListener('error',()=>{$('schematic-loading').textContent='此页暂时无法显示，请打开原始 PDF。';});
  $('schematic-button').addEventListener('click',()=>{
    schematicReturnFocus = document.activeElement;
    releaseKeys();
    $('schematic-dialog').showModal();
    document.body.classList.add('schematic-open');
    $('schematic-button').setAttribute('aria-expanded','true');
    $('schematic-button').classList.add('active');
    showSchematicPage(schematicPage);
    $('schematic-page-select').focus();
  });
  $('schematic-dialog').addEventListener('close',()=>{
    document.body.classList.remove('schematic-open');
    $('schematic-button').setAttribute('aria-expanded','false');
    $('schematic-button').classList.remove('active');
    schematicReturnFocus?.focus({preventScroll:true});
  });
  $('schematic-page-select').addEventListener('change',e=>showSchematicPage(e.target.value));
  $('schematic-prev').addEventListener('click',()=>showSchematicPage(schematicPage-1));
  $('schematic-next').addEventListener('click',()=>showSchematicPage(schematicPage+1));
  $('schematic-zoom').addEventListener('change',()=>{applySchematicZoom();$('schematic-viewport').scrollTo({top:0,left:0,behavior:'instant'});});

  function showInfo(title, eyebrow, content) { $('info-title').textContent=title; $('info-eyebrow').textContent=eyebrow; $('info-content').replaceChildren(...content); $('info-dialog').showModal(); }
  $('about-button').addEventListener('click',() => {
    const settings = node('button', 'button secondary full-width', '软件更新与设置');
    settings.id = 'about-settings-button';
    settings.addEventListener('click', () => { $('info-dialog').close(); $('settings-dialog').showModal(); });
    showInfo('CIMC Studio','PREVIEW 0.4',[node('p','','Windows、Linux 与浏览器共用的嵌入式仿真工作台。'),node('p','','共同烧录 Bootloader 与多个 ARM 应用，从选定向量启动。'),node('p','','当前为功能预览版，具体外设支持范围以交付文档和运行诊断为准。CIMC Studio 为独立开发项目，非赛事官方软件。'),settings]);
  });
  $('board-info-button').addEventListener('click',() => {
    const content = [];
    for (const [label,value] of [['板卡',board?.name || 'GD32F470 V1.0'],['资料状态',board?.verified ? '已核验' : 'V1 原理图已核对；外设功能为子集'],['可见端点',String(board?.pins?.length || 0)],['线路规则','固定网络只读；仅增删自己的跳线']]) { const row=node('div','info-row');row.append(node('span','',label),node('strong','',value));content.push(row); }
    if (board?.verified === false) content.push(node('p','','连接按 V1.0 原理图核对。视图表示接线拓扑，不表示 PCB 物理位置。ADC 旋钮固定接 PC0；SPI Flash 固定接 PB12–PB15。被板载外设占用的引脚已锁定，用户只能从空闲 GPIO 给 LED/KEY 添加跳线。'));
    if (board?.notes?.length) content.push(node('p','',Array.isArray(board.notes) ? board.notes.join('\n') : board.notes));
    showInfo('开发板信息','BOARD PROFILE',content);
  });

  $('save-project').addEventListener('click',async () => { try { const result=await api('/api/project');saveFile(`cimc-project-${stamp()}.json`,JSON.stringify(result.project||result,null,2));toast('固件、启动设置与接线工程已保存。'); } catch(error) { toast(error.message,true); } });
  $('import-project').addEventListener('click',() => $('project-file').click());
  $('project-file').addEventListener('change',async e => { const file=e.target.files[0];if(!file)return;try { const project=JSON.parse(await file.text());if(await command('project_load',{project})){serialCutoff=-1;diagnosticCutoff=0;toast(project.version >= 3 ? '固件与接线工程已恢复。' : '旧版接线工程已恢复。');} }catch(error){toast(`无法打开工程文件：${error.message}`,true);}finally{e.target.value='';} });
  $('export-button').addEventListener('click',async () => { if(activePanel==='wires'){$('save-project').click();return;} if(activePanel==='diagnostics'){saveFile(`cimc-diagnostics-${stamp()}.json`,JSON.stringify(state?.diagnostics||[],null,2));return;} const lines=(state?.serial||[]).map(e=>`[${logTime(e.time)}] [${e.channel}] [${e.direction}] ${e.text??e.hex??''}`);saveFile(`cimc-serial-${stamp()}.txt`,lines.join('\n'),'text/plain;charset=utf-8');toast('串口日志已导出。'); });
  $('clear-button').addEventListener('click',() => { if(activePanel==='wires'){toast('请使用每条跳线旁的删除按钮，避免误删接线。');return;} if(activePanel==='diagnostics'){diagnosticCutoff=(state?.diagnostics||[]).length;renderDiagnostics(true);return;} serialCutoff=Math.max(-1,...(state?.serial||[]).map((e,i)=>Number(e.id)||i));renderSerial(true);toast('已清空当前日志显示。'); });

  function applyPreferences(){document.body.classList.toggle('show-pin-labels',preferences.labels);document.body.classList.toggle('reduce-motion',preferences.motion);$('setting-labels').checked=preferences.labels;$('setting-motion').checked=preferences.motion;$('setting-shortcuts').checked=preferences.shortcuts;$('setting-updates').checked=preferences.autoUpdates;try{localStorage.setItem('cimc.studio.preferences',JSON.stringify(preferences));}catch{}}
  for(const [id,key] of [['setting-labels','labels'],['setting-motion','motion'],['setting-shortcuts','shortcuts'],['setting-updates','autoUpdates']])$(id).addEventListener('change',e=>{preferences[key]=e.target.checked;applyPreferences();if(key==='autoUpdates'&&e.target.checked)void checkUpdates(false);});

  function updateLink(url) {
    try { const target = new URL(url); return target.origin === 'https://github.com' && target.pathname.startsWith('/Epiphany-Lucky/cimc-simulator/releases/') && !target.username && !target.password ? target.href : null; }
    catch { return null; }
  }
  async function checkUpdates(manual) {
    if (checkingUpdate || sessionExited) return;
    checkingUpdate = true; lastUpdateAttempt = Date.now();
    $('check-updates').disabled = true;
    $('update-status').textContent = '正在检查更新…';
    try {
      const result = await api('/api/updates' + (manual ? '?force=1' : ''));
      if (sessionExited) return;
      $('update-current').textContent = `当前版本 ${result.currentVersion}`;
      $('update-status').textContent = result.message;
      const release = updateLink(result.releaseUrl);
      const available = result.status === 'ok' && result.available && !!release;
      $('settings-button').classList.toggle('has-update', available);
      $('about-button').classList.toggle('has-update', available);
      $('about-button').setAttribute('aria-label', available ? '关于 CIMC Studio，有新版本可用' : '关于 CIMC Studio');
      $('settings-button').setAttribute('aria-label', available ? '设置，有新版本可用' : '设置');
      $('update-downloads').replaceChildren();
      $('update-downloads').hidden = !available;
      if (available) {
        const choices = result.platform === 'windows'
          ? [['Windows 安装包', result.assets?.windowsInstaller], ['HTML 版', result.assets?.html]]
          : [['Ubuntu / Debian 安装包', result.assets?.linuxDeb], ['Linux 便携包', result.assets?.linuxPortable]];
        choices.push(['查看更新说明', release]);
        for (const [label, value] of choices) {
          const url = updateLink(value); if (!url) continue;
          const link = node('a', 'update-link', label); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
          $('update-downloads').append(link);
        }
        if (notifiedVersion !== result.latestVersion) {
          notifiedVersion = result.latestVersion;
          toast(`CIMC Studio ${result.latestVersion} 已发布，可在“设置”中下载更新。`);
        }
      }
    } catch {
      $('update-status').textContent = '暂时无法检查更新，请检查网络后重试。仿真可继续使用。';
    } finally {
      checkingUpdate = false; $('check-updates').disabled = sessionExited;
    }
  }
  $('check-updates').addEventListener('click', () => void checkUpdates(true));
  function periodicUpdate() { if (preferences.autoUpdates && connected && !document.hidden && Date.now() - lastUpdateAttempt >= 6 * 60 * 60 * 1000) void checkUpdates(false); }
  setInterval(periodicUpdate, 60 * 1000);
  document.addEventListener('visibilitychange', periodicUpdate);
  function editing(){return ['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)||document.activeElement?.getAttribute('role')==='slider'||document.querySelector('dialog[open]');}
  window.addEventListener('keydown',e=>{if(document.querySelector('dialog[open]')){if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='o')e.preventDefault();return;}if(e.key==='Escape'){clearPinSelection();$('board-card').classList.remove('expanded');}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='o'){e.preventDefault();$('firmware-file').click();return;}if(editing())return;if(e.code==='Space'&&document.activeElement?.tagName!=='BUTTON'){e.preventDefault();if(!e.repeat&&!$('run-button').disabled)$('run-button').click();}if(preferences.shortcuts&&/^[1-6]$/.test(e.key)&&!e.repeat){e.preventDefault();void pressKey(Number(e.key)-1,true);}});
  window.addEventListener('keyup',e=>{if(document.querySelector('dialog[open]'))return;if(/^[1-6]$/.test(e.key))void pressKey(Number(e.key)-1,false);});
  window.addEventListener('blur',releaseKeys);
  document.addEventListener('visibilitychange',()=>{if(document.hidden)releaseKeys();});

  let dragDepth=0;
  document.addEventListener('dragenter',e=>{if(e.dataTransfer?.types.includes('Files')){e.preventDefault();dragDepth++;$('drop-cover').classList.add('active');}});
  document.addEventListener('dragover',e=>{if(e.dataTransfer?.types.includes('Files'))e.preventDefault();});
  document.addEventListener('dragleave',e=>{if(e.dataTransfer?.types.includes('Files')){dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)$('drop-cover').classList.remove('active');}});
  document.addEventListener('drop',e=>{e.preventDefault();dragDepth=0;$('drop-cover').classList.remove('active');const files=e.dataTransfer?.files;if(!files?.length)return;if($('firmware-set-dialog').open){addFirmwareFiles(files);return;}if(document.querySelector('dialog[open]'))return;if(files.length>1){openFirmwareSet();addFirmwareFiles(files);}else prepareFile(files[0]);});

  buildHardwareControls(6,6);applyPreferences();updateEnabled();renderWires([]);renderDiagnostics(true);
  fetch('board-v1.json').then(r=>r.ok?r.json():Promise.reject()).then(setBoard).catch(()=>{});
  void poll();
})();
