(function () {
  const API_URL = (window.location.hostname === 'localhost' || window.location.protocol === 'file:')
    ? 'http://localhost:8000'
    : '';
  const jwt = localStorage.getItem('jwt');
  const rol = localStorage.getItem('user_rol');

  if (!jwt || rol !== 'anfitrion') {
    window.location.href = '../login.html';
    return;
  }

  window.cerrarSesionAnfitrion = function () {
    localStorage.clear();
    sessionStorage.clear();
    window.location.href = '../login.html';
  };

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  const pagina = window.location.pathname.split('/').pop() || 'alojamientosa.html';
  const hostName = localStorage.getItem('reserva_nombre') || 'Anfitrión';
  const iniciales = hostName.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase() || 'AN';

  const idAlojCount = pagina === 'alojamientosa.html' ? 'navPropCount' : 'countPropiedades';
  const idResCount = pagina === 'reservacionesa.html' ? 'navCount' : 'countReservas';

  const cAlojCache = sessionStorage.getItem('en_host_aloj') || '0';
  const cResCache = sessionStorage.getItem('en_host_res') || '0';

  const sidebar = document.querySelector('aside.sidebar');
  if (sidebar) {
    sidebar.innerHTML = `
      <a class="brand" href="alojamientosa.html" aria-label="Entre Nubes">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 22V12M12 12c0-4 3-7 7-7 0 4-3 7-7 7Zm0 0c0-4-3-7-7-7 0 4 3 7 7 7Zm0-10c0-2-1.5-4-4-4 0 2 1.5 4 4 4Z" fill="currentColor" stroke="none"/>
        </svg>
        <span>Entre Nubes<small>Panel anfitrión</small></span>
      </a>

      <div class="nav-group">
        <div class="nav-label">General</div>
        <a class="nav-link ${pagina === 'alojamientosa.html' ? 'active' : ''}" href="alojamientosa.html">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="m3 10 9-7 9 7v10a2 2 0 0 1-2 2h-4v-7h-6v7H5a2 2 0 0 1-2-2Z"/></svg>
          Alojamientos
          <span class="count" id="${idAlojCount}" data-side-count="alojamientos">${cAlojCache}</span>
        </a>
        <a class="nav-link ${pagina === 'reservacionesa.html' ? 'active' : ''}" href="reservacionesa.html">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>
          Reservaciones
          <span class="count" id="${idResCount}" data-side-count="reservaciones">${cResCache}</span>
        </a>
        <a class="nav-link ${pagina === 'huespedesa.html' ? 'active' : ''}" href="huespedesa.html">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
          Huéspedes
        </a>
      </div>

      <div class="nav-group">
        <div class="nav-label">Contenido</div>
        <a class="nav-link ${pagina === 'resenasa.html' ? 'active' : ''}" href="resenasa.html">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="m12 3 3 6 6 .9-4.5 4.2 1 6L12 17l-5.5 3 1-6L3 9.9 9 9l3-6Z"/></svg>
          Reseñas
        </a>
        <a class="nav-link ${pagina === 'reportesa.html' ? 'active' : ''}" href="reportesa.html">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M4 12h16M4 18h10"/></svg>
          Reportes
        </a>
        <a class="nav-link ${pagina === 'configuraciona.html' ? 'active' : ''}" href="configuraciona.html">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/></svg>
          Configuración
        </a>
        <a class="nav-link ${pagina === 'perfila.html' ? 'active' : ''}" href="perfila.html">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>
          Perfil
        </a>
      </div>

      <div class="sidebar-foot">
        <div class="avatar-sm" id="hostAvatar">${esc(iniciales)}</div>
        <div class="who"><span id="hostName">${esc(hostName)}</span><small>Anfitrión</small></div>
        <button class="sidebar-logout" type="button" onclick="cerrarSesionAnfitrion()">Salir</button>
      </div>
    `;
  }

  // Contadores del sidebar (solo propiedades y reservas del anfitrión del JWT)
  const headers = { 'Authorization': `Bearer ${jwt}` };

  fetch(`${API_URL}/api/anfitrion/alojamientos`, { headers })
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!Array.isArray(data)) return;
      sessionStorage.setItem('en_host_aloj', String(data.length));
      const el = document.querySelector('[data-side-count="alojamientos"]');
      if (el) el.textContent = data.length;
    })
    .catch(() => {});

  fetch(`${API_URL}/api/anfitrion/reservaciones`, { headers })
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!Array.isArray(data)) return;
      sessionStorage.setItem('en_host_res', String(data.length));
      const el = document.querySelector('[data-side-count="reservaciones"]');
      if (el) el.textContent = data.length;
    })
    .catch(() => {});
})();