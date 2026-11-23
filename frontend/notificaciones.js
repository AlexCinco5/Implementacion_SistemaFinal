(function () {
  const jwt = localStorage.getItem('jwt');
  if (!jwt) return;

  const API_URL = (window.location.hostname === 'localhost' || window.location.protocol === 'file:')
    ? 'http://localhost:8000'
    : '';
  const rol = localStorage.getItem('user_rol') || 'huesped';
  const path = window.location.pathname;
  const enAnfitrion = path.includes('/panelanfitrion/');
  const enAdmin = path.includes('/paneladmin/');
  const enSubcarpeta = enAnfitrion || enAdmin;

  function esc(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function formatoFecha(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleString('es-MX', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function destinoNotificacion(n) {
    if (rol === 'admin') {
      if (enAdmin) return 'reservaciones.html';
      return enSubcarpeta ? '../paneladmin/reservaciones.html' : 'paneladmin/reservaciones.html';
    }
    if (rol === 'anfitrion') {
      if (enAnfitrion) return 'reservacionesa.html';
      return enSubcarpeta ? '../panelanfitrion/reservacionesa.html' : 'panelanfitrion/reservacionesa.html';
    }
    const prefijo = enSubcarpeta ? '../' : '';
    return n.reservacion_id ? `${prefijo}recibo.html?id=${n.reservacion_id}` : `${prefijo}usuario.html`;
  }

  function inyectarEstilos() {
    if (document.getElementById('en-notif-styles')) return;
    const style = document.createElement('style');
    style.id = 'en-notif-styles';
    style.textContent = `
      .en-notif-wrap{position:relative;display:inline-flex;align-items:center}
      .en-notif-btn{
        width:40px;height:40px;border-radius:50%;border:1px solid #e2e8de;background:#fff;
        display:grid;place-items:center;position:relative;cursor:pointer;color:#1a2e20;
        transition:border-color .2s,box-shadow .2s
      }
      .en-notif-btn:hover{border-color:#2d5a3d;box-shadow:0 2px 8px rgba(30,61,40,.10)}
      .en-notif-btn svg{width:18px;height:18px}
      .en-notif-badge{
        position:absolute;top:-4px;right:-4px;min-width:18px;height:18px;padding:0 5px;
        border-radius:999px;background:#c8912f;color:#fff;font-size:11px;font-weight:700;
        display:none;align-items:center;justify-content:center;border:2px solid #fff
      }
      .en-notif-badge.show{display:inline-flex}
      .en-notif-panel{
        position:absolute;top:48px;right:0;width:360px;max-width:calc(100vw - 24px);
        background:#fff;border:1px solid #e2e8de;border-radius:16px;
        box-shadow:0 12px 32px rgba(30,61,40,.16);z-index:1200;display:none;overflow:hidden
      }
      .en-notif-panel.open{display:block}
      .en-notif-head{
        display:flex;align-items:center;justify-content:space-between;
        padding:14px 16px;border-bottom:1px solid #e2e8de;background:#fafaf5
      }
      .en-notif-head strong{font:700 14px/1 Montserrat,sans-serif;color:#1a2e20}
      .en-notif-all{
        font-size:12px;font-weight:600;color:#2d5a3d;background:none;border:0;cursor:pointer;padding:4px 6px;border-radius:6px
      }
      .en-notif-all:hover{background:#e6efe8}
      .en-notif-list{max-height:380px;overflow-y:auto}
      .en-notif-empty{padding:26px 16px;text-align:center;color:#6b7a6f;font-size:13px}
      .en-notif-item{
        display:block;width:100%;text-align:left;padding:13px 16px;border:0;
        border-bottom:1px solid #eef2ec;background:#fff;cursor:pointer;transition:background .15s
      }
      .en-notif-item:last-child{border-bottom:0}
      .en-notif-item:hover{background:#f2f5ee}
      .en-notif-item.unread{background:#e6efe8}
      .en-notif-item.unread:hover{background:#dbe7de}
      .en-notif-title{
        display:flex;align-items:center;gap:7px;font-size:13px;font-weight:700;color:#1a2e20;margin-bottom:3px
      }
      .en-notif-dot{width:7px;height:7px;border-radius:50%;background:#2d5a3d;flex:0 0 7px}
      .en-notif-msg{font-size:12.5px;color:#4a5a4f;line-height:1.4;margin:0}
      .en-notif-time{font-size:11px;color:#6b7a6f;margin-top:5px}
    `;
    document.head.appendChild(style);
  }

  function montarContenedor() {
    let destino = document.querySelector('.nav-actions') || document.querySelector('.top-actions');
    if (!destino) {
      const topbar = document.querySelector('.topbar');
      if (topbar) {
        if (!topbar.querySelector('.spacer')) {
          const spacer = document.createElement('div');
          spacer.className = 'spacer';
          topbar.appendChild(spacer);
        }
        destino = document.createElement('div');
        destino.className = 'top-actions';
        topbar.appendChild(destino);
      }
    }
    if (!destino) return null;

    // Si la página tenía un botón estático de campana (como reportes.html), lo reemplazamos
    const campanaEstatica = destino.querySelector('button[aria-label="Notificaciones"]');
    if (campanaEstatica) campanaEstatica.remove();

    const wrap = document.createElement('div');
    wrap.className = 'en-notif-wrap';
    wrap.id = 'enNotifWrap';
    wrap.innerHTML = `
      <button class="en-notif-btn" id="enNotifBtn" type="button" aria-label="Notificaciones">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/>
          <path d="M13.7 21a2 2 0 0 1-3.4 0"/>
        </svg>
        <span class="en-notif-badge" id="enNotifBadge">0</span>
      </button>
      <div class="en-notif-panel" id="enNotifPanel">
        <div class="en-notif-head">
          <strong>Notificaciones</strong>
          <button class="en-notif-all" id="enNotifReadAll" type="button">Marcar leídas</button>
        </div>
        <div class="en-notif-list" id="enNotifList">
          <div class="en-notif-empty">Cargando avisos...</div>
        </div>
      </div>
    `;

    if (destino.classList.contains('nav-actions')) {
      destino.insertBefore(wrap, destino.firstChild);
    } else {
      destino.appendChild(wrap);
    }
    return wrap;
  }

  async function cargarNotificaciones() {
    try {
      const res = await fetch(`${API_URL}/api/notificaciones`, {
        headers: { 'Authorization': `Bearer ${jwt}` }
      });
      if (!res.ok) return;
      const data = await res.json();
      const lista = data.notificaciones || [];
      const sinLeer = data.sin_leer || 0;
      sessionStorage.setItem('en_notif_sin_leer', String(sinLeer));

      const badge = document.getElementById('enNotifBadge');
      const listEl = document.getElementById('enNotifList');
      if (badge) {
        badge.textContent = sinLeer > 9 ? '9+' : String(sinLeer);
        badge.classList.toggle('show', sinLeer > 0);
      }

      if (listEl) {
        if (!lista.length) {
          listEl.innerHTML = '<div class="en-notif-empty">Aún no tienes notificaciones.</div>';
        } else {
          listEl.innerHTML = lista.map((n) => `
            <button type="button" class="en-notif-item ${n.leida ? '' : 'unread'}" data-id="${esc(n.id)}" data-res="${esc(n.reservacion_id || '')}">
              <div class="en-notif-title">
                ${n.leida ? '' : '<span class="en-notif-dot"></span>'}
                <span>${esc(n.titulo)}</span>
              </div>
              <p class="en-notif-msg">${esc(n.mensaje)}</p>
              <div class="en-notif-time">${esc(formatoFecha(n.creado_en))}</div>
            </button>
          `).join('');

          listEl.querySelectorAll('.en-notif-item').forEach((btn) => {
            btn.addEventListener('click', async () => {
              const notifId = btn.dataset.id;
              const resId = btn.dataset.res;
              try {
                await fetch(`${API_URL}/api/notificaciones/${notifId}/leer`, {
                  method: 'PUT',
                  headers: { 'Authorization': `Bearer ${jwt}` }
                });
              } catch (_) {}
              window.location.href = destinoNotificacion({ reservacion_id: resId });
            });
          });
        }
      }

      window.dispatchEvent(new CustomEvent('en:notificaciones', { detail: data }));
    } catch (e) {
      console.error('Error cargando notificaciones:', e);
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    inyectarEstilos();
    const wrap = montarContenedor();
    if (!wrap) return;

    const btn = document.getElementById('enNotifBtn');
    const panel = document.getElementById('enNotifPanel');
    const btnAll = document.getElementById('enNotifReadAll');

    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      panel.classList.toggle('open');
      if (panel.classList.contains('open')) cargarNotificaciones();
    });

    document.addEventListener('click', (e) => {
      if (!wrap.contains(e.target)) panel.classList.remove('open');
    });

    btnAll.addEventListener('click', async () => {
      try {
        await fetch(`${API_URL}/api/notificaciones/leer-todas`, {
          method: 'PUT',
          headers: { 'Authorization': `Bearer ${jwt}` }
        });
        cargarNotificaciones();
      } catch (_) {}
    });

    window.cargarNotificacionesEntreNubes = cargarNotificaciones;
    
    const cachedCount = parseInt(sessionStorage.getItem('en_notif_sin_leer') || '0', 10);
    const badgeInit = document.getElementById('enNotifBadge');
    if (badgeInit && cachedCount > 0) {
      badgeInit.textContent = cachedCount > 9 ? '9+' : String(cachedCount);
      badgeInit.classList.add('show');
    }

    cargarNotificaciones();
    setInterval(() => {
      if (!document.hidden) cargarNotificaciones();
    }, 30000);
  });
})();