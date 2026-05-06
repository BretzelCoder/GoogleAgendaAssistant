/**
 * js/gcal.js
 * Wrapper autour de l'API Google Calendar (REST).
 */

const GCal = (() => {

  const SCOPES   = 'https://www.googleapis.com/auth/calendar';
  const API_BASE = 'https://www.googleapis.com/calendar/v3';

  let _accessToken     = null;
  let _tokenClient     = null;
  let _onTokenCallback = null;

  // ── Auth ───────────────────────────────────────────────────────────────────

  function init(clientId, onToken) {
    _onTokenCallback = onToken;

    _tokenClient = google.accounts.oauth2.initTokenClient({
      client_id: clientId,
      scope: SCOPES,
      callback: (response) => {
        if (response.error) {
          console.warn('[GCal]', response.error, response.error_description);
          _accessToken = null;
          if (response.error === 'popup_closed_by_user') return;
          onToken(null, _friendlyError(response.error));
          return;
        }
        _accessToken = response.access_token;
        onToken(_accessToken);
      },
      error_callback: (err) => {
        console.warn('[GCal] error_callback', err);
        _accessToken = null;
        onToken(null, _friendlyError(err.type));
      },
    });

    // Signale que l'init est terminé → affiche le bouton de connexion
    onToken(null);
  }

  function _friendlyError(error) {
    const map = {
      'access_denied':                   '❌ Accès refusé. Vérifiez que votre email est dans les utilisateurs test Google Cloud.',
      'invalid_client':                  '❌ Client ID invalide ou origine non autorisée dans Google Cloud Console.',
      'origin_mismatch':                 '❌ Origine non autorisée. Vérifiez http://localhost:8080 dans les origines JavaScript autorisées.',
      'unauthorized_client':             '❌ Application non autorisée. Vérifiez la configuration OAuth Google Cloud.',
      'popup_failed_to_open':            '❌ La popup Google a été bloquée par le navigateur. Autorisez les popups pour localhost:8080, puis réessayez.',
      'idpiframe_initialization_failed': '❌ Échec initialisation Google. Désactivez votre bloqueur de publicités ou vérifiez votre connexion.',
    };
    return map[error] || `❌ Erreur Google (${error}). Vérifiez la console pour plus de détails.`;
  }

  /** Connexion interactive — ouvre le sélecteur de compte Google */
  function requestToken() {
    if (!_tokenClient) { alert('GCal non initialisé.'); return; }
    _tokenClient.requestAccessToken({ prompt: 'select_account' });
  }

  function revokeToken() {
    if (_accessToken) {
      google.accounts.oauth2.revoke(_accessToken, () => {});
      _accessToken = null;
    }
    if (_onTokenCallback) _onTokenCallback(null);
  }

  function isAuthenticated() { return !!_accessToken; }

  // ── Helpers HTTP ───────────────────────────────────────────────────────────

  async function apiFetch(path, options = {}) {
    if (!_accessToken) throw new Error('Non authentifié.');
    const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
    const response = await fetch(url, {
      ...options,
      headers: {
        'Authorization': `Bearer ${_accessToken}`,
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      },
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({ error: { message: response.statusText } }));
      throw new Error(err.error?.message || `HTTP ${response.status}`);
    }
    return response.status === 204 ? null : response.json();
  }

  // ── Agendas ────────────────────────────────────────────────────────────────

  async function listCalendars() {
    const data = await apiFetch('/users/me/calendarList');
    return data.items || [];
  }

  // ── Détection doublons ─────────────────────────────────────────────────────

  async function findByUID(calendarId, iCalUID) {
    try {
      const data = await apiFetch(
        `/calendars/${encodeURIComponent(calendarId)}/events?iCalUID=${encodeURIComponent(iCalUID)}&showDeleted=false&singleEvents=false`
      );
      return data.items?.[0] || null;
    } catch { return null; }
  }

  // ── Import ─────────────────────────────────────────────────────────────────

  async function importEvent(calendarId, eventBody, strategy = 'skip') {
    const uid = eventBody.iCalUID;
    let existing = uid ? await findByUID(calendarId, uid) : null;

    if (existing) {
      if (strategy === 'skip')   return { status: 'skipped', message: 'Doublon ignoré.' };
      if (strategy === 'update') {
        await apiFetch(`/calendars/${encodeURIComponent(calendarId)}/events/${existing.id}`,
          { method: 'PUT', body: JSON.stringify(eventBody) });
        return { status: 'updated', message: 'Mis à jour.' };
      }
      // duplicate : insert sans UID
      const body = Object.fromEntries(Object.entries(eventBody).filter(([k]) => k !== 'iCalUID'));
      await apiFetch(`/calendars/${encodeURIComponent(calendarId)}/events`,
        { method: 'POST', body: JSON.stringify(body) });
      return { status: 'imported', message: 'Dupliqué.' };
    }

    if (uid) {
      await apiFetch(`/calendars/${encodeURIComponent(calendarId)}/events/import`,
        { method: 'POST', body: JSON.stringify(eventBody) });
    } else {
      await apiFetch(`/calendars/${encodeURIComponent(calendarId)}/events`,
        { method: 'POST', body: JSON.stringify(eventBody) });
    }
    return { status: 'imported', message: 'Importé.' };
  }

  async function importAll(calendarId, events, strategy = 'skip', onProgress = null) {
    const report = { imported: 0, updated: 0, skipped: 0, errors: [], results: [] };
    for (let i = 0; i < events.length; i++) {
      const ev = events[i];
      let result;
      try {
        result = await importEvent(calendarId, ev, strategy);
        result.summary = ev.summary || '(sans titre)';
      } catch (e) {
        result = { status: 'error', message: e.message, summary: ev.summary || '(sans titre)' };
      }
      report.results.push(result);
      if (result.status === 'imported') report.imported++;
      else if (result.status === 'updated') report.updated++;
      else if (result.status === 'skipped') report.skipped++;
      else report.errors.push(`${result.summary} : ${result.message}`);
      if (onProgress) onProgress(i + 1, events.length, result);
    }
    return report;
  }

  return { init, requestToken, revokeToken, isAuthenticated, listCalendars, importAll };
})();
