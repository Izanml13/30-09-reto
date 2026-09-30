/* ============================================================
   ASIX Speech-to-Text · logica del cliente
   ============================================================ */
'use strict';

const $ = (sel) => document.querySelector(sel);

const API = {
  health:      '/api/health',
  groundtruth: '/api/groundtruth',
  transcribe:  '/api/transcribe',
  evaluate:    '/api/evaluate',
};

/* Estado local: resultados por audio, para no perderlos al recargar. */
const LS_KEY = 'stt_resultados_v1';

const estado = {
  reconocimiento: null,
  leyendo: false,
  resultados: cargarResultados(),
  verdadTerreno: {},
};

/* ---------------------------------------------------------
   Utilidades
   --------------------------------------------------------- */
function cargarResultados() {
  try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; }
  catch { return {}; }
}

function guardarResultados() {
  try { localStorage.setItem(LS_KEY, JSON.stringify(estado.resultados)); }
  catch { /* modo privado o cuota llena: se ignora */ }
}

function nombreClave(fichero) {
  return (fichero || '').split('/').pop().replace(/\.[^.]+$/, '');
}

function escapar(txt) {
  const d = document.createElement('div');
  d.textContent = txt ?? '';
  return d.innerHTML;
}

function ponerPill(el, texto, clase) {
  el.textContent = texto;
  el.className = 'pill ' + (clase || 'pill--wait');
}

/* ---------------------------------------------------------
   Diagnostico del entorno para errores de microfono

   `not-allowed` tiene causas muy distintas segun donde se
   ejecute la pagina, y un mensaje generico no ayuda a
   solucionarlo: por eso se detecta el entorno real.
   --------------------------------------------------------- */
function entorno() {
  const ua = navigator.userAgent;
  const electron = /OpenCode|Electron/i.test(ua);
  return {
    // Electron / app de escritorio: no pide permiso de microfono al usuario.
    // Ojo: la UA de Electron INCLUYE "Chrome/...", asi que no se puede negar
    // para detectarlo; hay que comprobarlo primero que el resto.
    enApp: electron,
    electron,
    safari: !electron && /Safari/i.test(ua) && !/Chrome|Chromium|Edg\//i.test(ua),
    chrome: !electron && /Chrome\//i.test(ua),
    // isSecureContext es condicion para getUserMedia y SpeechRecognition.
    inseguro: !window.isSecureContext,
    url: location.href,
  };
}

function resolverErrorMic(codigo) {
  const e = entorno();
  const titulos = {
    'not-allowed': 'Permiso de micrófono denegado',
    'service-not-allowed': 'Servicio de voz bloqueado',
    'no-speech': 'No se ha detectado voz',
    'audio-capture': 'No hay micrófono disponible',
    'network': 'Fallo de red en el reconocimiento',
    'aborted': 'Reconocimiento cancelado',
  };
  const t = titulos[codigo] || 'Error del navegador';

  let cuerpo = '';

  if (codigo === 'not-allowed' || codigo === 'service-not-allowed') {
    if (e.enApp) {
      cuerpo = `
        <p><strong>Esto no es un fallo de la web ni del permiso de macOS.</strong>
        OpenCode deniega el microfono desde su propio codigo, con un
        <code>setPermissionRequestHandler</code> que solo permite
        <code>clipboard-sanitized-write</code> y <code>notifications</code>.
        Es fijo y no se puede cambiar: ninguna configuracion de sistema lo
        arregla.</p>
        <p><strong>Usa un navegador normal</strong> para la Opcion A:</p>
        <ol>
          <li>Abre <code>http://127.0.0.1:5000</code> en <strong>Safari</strong>
            o <strong>Chrome</strong>. (Safari ya esta en tu equipo.)</li>
          <li>Cuando pida el microfono, pulsa <strong>Permitir</strong>.</li>
          <li>Pulsa «Empezar a escuchar» y habla.</li>
        </ol>
        <p><em>Alternativa sin microfono:</em> el panel B (endpoint Flask)
        funciona dentro de OpenCode, porque solo sube ficheros y no necesita
        permiso alguno.</p>`;
    } else if (e.safari) {
      cuerpo = `
        <p>Safari pide el permiso una vez y después lo recuerda, pero macOS
        puede haberlo bloqueado para la app.</p>
        <ol>
          <li><strong>Safari → Ajustes → Webs → Micrófono:</strong>
            selecciona «Permitir» para <code>127.0.0.1</code>.</li>
          <li><strong>Mac → Ajustes del Sistema → Privacidad y seguridad →
            Micrófono:</strong> marca <em>Safari</em>. Si Safari no aparece,
            añádelo con el botón «+».</li>
          <li>Reinicia Safari y vuelve a probar.</li>
        </ol>
        <p><em>Nota:</em> la Web Speech API en Safari es parcial. Si no
        reconoce, instala Chrome (<code>brew install --cask google-chrome</code>).</p>`;
    } else if (e.chrome) {
      cuerpo = `
        <ol>
          <li>Pulsa el <strong>candado 🔒 de la barra de direcciones</strong> →
            Permisos → Micrófono → «Permitir».</li>
          <li>Si no aparece candado, revisa
            <strong>Ajustes → Privacidad y seguridad → Micrófono</strong>
            en macOS y marca <em>Chrome</em>.</li>
          <li>Recarga la página: el permiso solo se aplica tras recargar.</li>
        </ol>`;
    } else {
      cuerpo = `
        <p>Este navegador (<code>${escapar(e.url)}</code>) no ha concedido el
        acceso al micrófono. Activa el permiso en el candado de la barra de
        direcciones y recarga la página.</p>`;
    }
  } else if (codigo === 'audio-capture') {
    cuerpo = `<p>Comprueba que hay un micrófono conectado y que macOS no lo
      desactiva para este navegador en
      <strong>Privacidad y seguridad → Micrófono</strong>.</p>`;
  } else if (codigo === 'network') {
    cuerpo = `<p>El navegador no pudo contactar con el servicio de
      reconocimiento. Revisa la conexión a Internet: a diferencia de la
      Opción&nbsp;B, la Web Speech API transmite el audio a Google desde el
      navegador.</p>`;
  } else if (codigo === 'no-speech') {
    cuerpo = `<p>Habla más cerca del micrófono. También puede deberse a que el
      volumen esté muy bajo o a que no hubo audio durante unos segundos.</p>`;
  }

  if (e.inseguro && codigo !== 'no-speech') {
    cuerpo += `<p><em>Aviso: el contexto no es seguro.</em> La Web Speech API
      solo funciona en <code>https://</code> o en <code>localhost</code>; no
      funciona en una IP de la LAN.</p>`;
  }

  return `<strong>${escapar(t)}.</strong> ${cuerpo}`;
}

function descargarTexto(nombre, texto) {
  const url = URL.createObjectURL(new Blob([texto], { type: 'text/plain;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = nombre;
  a.click();
  URL.revokeObjectURL(url);
}

/* ---------------------------------------------------------
   0. Estado del servidor
   --------------------------------------------------------- */
async function comprobarServidor() {
  const pill = $('#estado-servidor');
  const gem = $('#estado-gemini');
  try {
    const r = await fetch(API.health);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();

    ponerPill(pill, `Servidor activo · v${d.version}`, 'pill--ok');

    if (d.gemini.operativo) {
      ponerPill(gem, `Gemini operativo · ${d.config.gemini_model}`, 'pill--ok');
    } else {
      const textos = {
        sin_credencial: 'Sin API key · usarás mock',
        credencial_presente: 'Con API key · comprobando',
        bloqueado: 'Gemini bloqueado · usarás mock',
      };
      ponerPill(gem, textos[d.gemini.estado] || 'Gemini no disponible', 'pill--warn');

      // Se explica el motivo en la propia vista: si no, el usuario cree
      // que Gemini funciona cuando en realidad esta denegado.
      if (d.gemini.detalle) {
        gem.title = d.gemini.detalle;
        $('#panel-b .panel__head').insertAdjacentHTML(
          'afterend',
          '<div class="alerta alerta--warn"><strong>Gemini no operativo.</strong> ' +
          escapar(d.gemini.detalle) + '</div>'
        );
      }
    }
  } catch (e) {
    ponerPill(pill, 'Servidor no disponible', 'pill--err');
    ponerPill(gem, 'sin conexión', 'pill--err');
  }
}

/* ---------------------------------------------------------
   1. Panel A · Web Speech API
   --------------------------------------------------------- */
function comprobarSoporte() {
  const pill = $('#soporte-speech');
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SpeechRec) {
    ponerPill(pill, 'No soportado en este navegador', 'pill--err');
    $('#btn-empezar').disabled = true;
    document.querySelector('#texto-a .placeholder').textContent =
      'Este navegador no implementa la Web Speech API. Usa Chrome o Edge ' +
      '(Safari y Firefox no la ofrecen de forma estable).';
    return null;
  }
  ponerPill(pill, 'Soportada', 'pill--ok');

  // Aviso preventivo: aunque la API exista, en ciertos entornos el permiso
  // esta denegado de origen. Avisar antes de que el usuario pulse ahorra el
  // intento fallido.
  const e = entorno();
  const panel = $('#panel-a');
  if (e.enApp) {
    ponerPill(pill, 'Bloqueado en OpenCode', 'pill--warn');
    panel.querySelector('.panel__head').insertAdjacentHTML(
      'afterend',
      '<div class="alerta alerta--warn"><strong>El microfono esta bloqueado en ' +
      'OpenCode.</strong> OpenCode deniega el permiso de <code>media</code> en su ' +
      'propio <code>setPermissionRequestHandler</code>: solo admite ' +
      '<code>clipboard-sanitized-write</code> y <code>notifications</code>, y ' +
      'esto no es configurable. <strong>Abre ' +
      '<code>http://127.0.0.1:5000</code> en Safari o Chrome</strong> para ' +
      'usar la Opcion A.</div>'
    );
  }
  return SpeechRec;
}

function textoAcumulado(evResults) {
  let final = '';
  let provisional = '';

  // La propiedad de la API DOM es `results` (en ingles), NO `resultados`.
  // Usar `resultados` devuelve undefined y el `?? []` lo convierte en una
  // lista vacia, con lo que la transcripcion nunca se pintaba en pantalla.
  const lista = evResults
    || estado.reconocimiento?.results
    || null;

  if (!lista) return { final: '', provisional: '' };

  for (let i = 0; i < lista.length; i++) {
    const res = lista[i];
    // Se recorren TODOS los resultados (indice 0), no desde `resultIndex`:
// la cadena se reconstruye entera en cada pintado, y saltar los ya
// finalizados dejaria fuera el texto acumulado anterior.
    for (let j = 0; j < res.length; j++) {
      const alt = res[j];
      if (!alt) continue;
      const t = alt.transcript || '';
      if (alt.isFinal) final += t + ' ';
      else provisional += t;
    }
  }
  return { final: final.trim(), provisional: provisional.trim() };
}

function pintarVivo(evResults) {
  const caja = $('#texto-a');
  const { final, provisional } = textoAcumulado(evResults);

  if (!final && !provisional) {
    caja.innerHTML =
      '<span class="placeholder">Escuchando… di algo en español.</span>';
  } else {
    caja.innerHTML =
      escapar(final) +
      (provisional ? ` <span class="interino">${escapar(provisional)}</span>` : '');
  }
  const palabras = (final + ' ' + provisional).trim().split(/\s+/).filter(Boolean).length;
  $('#info-a').textContent = final
    ? `${palabras} palabras · provisional: ${provisional ? 'sí' : 'no'}`
    : '—';
}

function empezarEscucha() {
  const SpeechRec = comprobarSoporte();
  if (!SpeechRec) return;

  const rec = new SpeechRec();
  rec.lang = $('#idioma').value;
  rec.continuous = $('#continuo').checked;
  rec.interimResults = $('#interino').checked;
  rec.maxAlternatives = 1;

  rec.onstart = () => {
    estado.leyendo = true;
    $('#btn-empezar').disabled = true;
    $('#btn-parar').disabled = false;
    ponerPill($('#soporte-speech'), 'Grabando…', 'pill--live');
    $('#info-a').textContent = 'Escuchando…';
  };

  rec.onresult = (ev) => {
    estado.reconocimiento = rec;
    pintarVivo(ev.results);
  };

  rec.onerror = (ev) => {
    const clase = ev.error === 'no-speech' ? 'alerta--warn' : 'alerta--err';
    const msg = resolverErrorMic(ev.error);
    const caja = $('#texto-a');

    // Se borra el aviso anterior para que no se acumulen varios. La busqueda
    // se limita al panel A: el panel B tiene su propia alerta de Gemini.
    caja.parentElement.querySelectorAll('.alerta').forEach((n) => n.remove());
    caja.insertAdjacentHTML(
      'afterend', `<div class="alerta ${clase}">${msg}</div>`);
    $('#info-a').textContent = caja.nextElementSibling
      ? caja.nextElementSibling.textContent : msg;
  };

  rec.onend = () => {
    estado.leyendo = false;
    $('#btn-empezar').disabled = false;
    $('#btn-parar').disabled = true;
    ponerPill($('#soporte-speech'), 'Soportada', 'pill--ok');
    guardarResultadoWebSpeech();
  };

  estado.reconocimiento = rec;
  try {
    rec.start();
  } catch (e) {
    $('#info-a').textContent = 'No se pudo iniciar: ' + e.message;
  }
}

function pararEscucha() {
  try { estado.reconocimiento?.stop(); } catch { /* ya detenido */ }
}

function guardarResultadoWebSpeech() {
  const { final } = textoAcumulado();
  if (!final) return;
  // Sin identificador de audio no hay contra que comparar: se guarda aparte.
  const clave = 'microfono';
  estado.resultados[clave] = {
    metodo: 'Web Speech API',
    hipotesis: final,
    fichero: null,
    evaluable: true,
    ts: new Date().toISOString(),
  };
  guardarResultados();
}

/* ---------------------------------------------------------
   2. Panel B · endpoint Flask -> Gemini
   --------------------------------------------------------- */
function pintarJSON(obj) {
  $('#salida-b').innerHTML = escapar(JSON.stringify(obj, null, 2));
}

async function transcribir(e) {
  e.preventDefault();
  const input = $('#audio');
  if (!input.files.length) {
    alert('Primero elige un fichero de audio.');
    return;
  }

  const btn = $('#btn-enviar');
  const caja = $('#salida-b');
  btn.disabled = true;
  caja.innerHTML = '<span class="placeholder">Transcribiendo en el servidor…</span>';

  const fd = new FormData();
  fd.append('audio', input.files[0]);
  fd.append('language', $('#idioma-b').value);
  fd.append('provider', $('#proveedor-b').value);

  try {
    const r = await fetch(API.transcribe, { method: 'POST', body: fd });
    const cuerpo = await r.json().catch(() => ({ error: 'respuesta no JSON' }));
    pintarJSON(cuerpo);

    if (!r.ok) {
      caja.insertAdjacentHTML(
        'afterend',
        `<div class="alerta alerta--err"><strong>Error ${r.status}</strong> — ` +
        `${escapar(cuerpo.detalle || cuerpo.error || 'desconocido')}</div>`);
      return;
    }

    // El proveedor simulado no analiza el audio: no debe entrar en la comparativa.
    const evaluable = cuerpo.provider !== 'mock';
    let aviso = '';
    if (!evaluable) {
      aviso = `<div class="alerta alerta--warn">${escapar(
        cuerpo.warning || 'Respuesta simulada: no se ha analizado el audio.')}</div>`;
    }

    const clave = nombreClave(cuerpo.audio?.filename) || 'subida';
    estado.resultados[clave] = {
      metodo: cuerpo.provider,
      hipotesis: cuerpo.text || '',
      fichero: cuerpo.audio?.filename || null,
      evaluable,
      ts: new Date().toISOString(),
    };
    guardarResultados();
    if (aviso) caja.insertAdjacentHTML('afterend', aviso);
    pintarComparativa();
  } catch (err) {
    caja.innerHTML = '';
    caja.insertAdjacentHTML(
      'afterend',
      `<div class="alerta alerta--err">No se pudo contactar con el servidor: ${escapar(err.message)}</div>`);
  } finally {
    btn.disabled = false;
  }
}

/* ---------------------------------------------------------
   3. Panel C · comparativa (WER via /api/evaluate)
   --------------------------------------------------------- */
async function cargarVerdadTerreno() {
  try {
    const r = await fetch(API.groundtruth);
    if (!r.ok) return;
    const d = await r.json();
    for (const a of d.audios || []) {
      estado.verdadTerreno[a.archivo] = {
        id: a.id,
        referencia: a.referencia,
        voz: a.voz,
        nivel: a.nivel,
      };
    }
  } catch { /* sin audios generados todavia */ }
}

async function pedirWER(referencia, hipotesis, evaluable) {
  try {
    const r = await fetch(API.evaluate, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ referencia, hipotesis, evaluable }),
    });
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

function claseWer(pct) {
  if (pct == null || Number.isNaN(pct)) return 'wer--na';
  if (pct <= 5) return 'wer--bien';
  if (pct <= 20) return 'wer--medio';
  return 'wer--mal';
}

function celdaWER(w) {
  if (!w || !w.evaluable) {
    return `<td class="wer wer--na">n/d</td>`;
  }
  return `<td class="wer ${claseWer(w.wer_porcentaje)}">${w.wer_porcentaje}%</td>`;
}

async function pintarComparativa() {
  const cuerpo = $('#tabla-eval tbody');
  const claves = Object.keys(estado.resultados);

  if (!claves.length) {
    cuerpo.innerHTML = '<tr class="vacio"><td colspan="6">Todavía no hay resultados.</td></tr>';
    return;
  }

  const filas = [];
  let conApi = 0, evaluables = 0;

  for (const clave of claves) {
    const res = estado.resultados[clave];
    const gt = estado.verdadTerreno[res.fichero] ||
               Object.values(estado.verdadTerreno).find((v) => v.id === clave);

    const referencia = gt ? gt.referencia : '(sin referencia conocida)';
    const otros = claves.filter((k) => k !== clave).map((k) => estado.resultados[k]);

    const wApi = gt
      ? await pedirWER(referencia, res.evaluable ? res.hipotesis : '', res.evaluable)
      : null;
    const wEndpoint = otros.length && gt
      ? await pedirWER(referencia, otros[0].evaluable ? otros[0].hipotesis : '',
                       otros[0].evaluable)
      : null;

    if (wApi?.evaluable) { conApi++; evaluables++; }

    filas.push(`
      <tr>
        <td data-th="Audio"><strong>${escapar(gt ? gt.id : clave)}</strong><br>
            <span class="mono">${escapar(res.fichero || 'micrófono en vivo')}</span></td>
        <td data-th="Referencia" class="ref">${escapar(referencia)}</td>
        <td data-th="Web Speech API" class="mono">${escapar(res.evaluable ? (res.hipotesis || '—') : '—')}</td>
        <td data-th="Endpoint" class="mono">${otros.length
            ? escapar(otros[0].evaluable ? (otros[0].hipotesis || '—') : 'simulado (no evaluable)')
            : '—'}</td>
        ${celdaWER(wApi)}
        ${celdaWER(wEndpoint)}
      </tr>`);
  }

  cuerpo.innerHTML = filas.join('');
  ponerPill($('#estado-eval'),
    evaluables ? `${evaluables}/${claves.length} con WER medido` : 'sin WER medible',
    evaluables ? 'pill--ok' : 'pill--warn');
}

/* ---------------------------------------------------------
   Arranque
   --------------------------------------------------------- */
function conectarEventos() {
  $('#btn-empezar').addEventListener('click', empezarEscucha);
  $('#btn-parar').addEventListener('click', pararEscucha);
  $('#btn-limpiar-a').addEventListener('click', () => {
    $('#texto-a').innerHTML =
      '<span class="placeholder">Pulsa «Empezar a escuchar» y habla. El texto aparecerá aquí palabra a palabra.</span>';
    $('#info-a').textContent = '—';
  });
  $('#btn-copiar-a').addEventListener('click', () => {
    const { final } = textoAcumulado();
    descargarTexto('webspeech-transcripcion.txt', final || '(vacío)');
  });
  $('#form-b').addEventListener('submit', transcribir);

  $('#audio').addEventListener('change', (e) => {
    const label = e.target.closest('label.file');
    if (!label) return;
    const f = e.target.files[0];
    const texto = label.querySelector('.file__text strong');
    label.classList.toggle('tiene-fichero', !!f);
    // Se apunta al <strong> de .file__text, no al primer <span>: el primero
    // es .file__frame y escribir ahi borraria su icono SVG.
    if (texto) texto.textContent = f ? f.name : 'Elegir fichero de audio';
  });

  $('#btn-ejemplos').addEventListener('click', async () => {
    const ids = Object.values(estado.verdadTerreno).map((v) => v.id);
    if (!ids.length) {
      alert('No hay audios de prueba. Ejecuta ./scripts/generate_audios.sh');
      return;
    }
    alert('Los audios están en la carpeta audios/.\n' +
          'Súbelos uno a uno con el botón de arriba.\n\n' +
          'Lista:\n  ' + ids.join('\n  '));
  });
}

async function init() {
  conectarEventos();
  comprobarSoporte();
  await Promise.all([comprobarServidor(), cargarVerdadTerreno()]);
  await pintarComparativa();
  $('#pie-tec').textContent =
    navigator.userAgent.includes('Chrome') ? 'Chrome' :
    navigator.userAgent.includes('Safari') ? 'Safari' : 'otro navegador';
}

init();
