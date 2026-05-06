/**
 * js/parser.js
 * Parse les fichiers iCalendar (.ics) avec ical.js
 * et convertit les VEVENT en objets compatibles Google Calendar API.
 */

const ICSParser = (() => {

  // ── Helpers ────────────────────────────────────────────────────────────────

  function toISOString(jcalDate) {
    if (!jcalDate) return null;
    const dt = jcalDate.toJSDate();
    return dt.toISOString();
  }

  function formatDisplay(jcalDate) {
    if (!jcalDate) return '';
    const dt = jcalDate.toJSDate();
    if (jcalDate.isDate) {
      return dt.toLocaleDateString('fr-FR');
    }
    return dt.toLocaleString('fr-FR', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  }

  function getRruleString(vevent) {
    const rrule = vevent.getFirstProperty('rrule');
    if (!rrule) return null;
    const val = rrule.getFirstValue();
    return 'RRULE:' + val.toString();
  }

  function getExdates(vevent) {
    const exdates = vevent.getAllProperties('exdate');
    return exdates.map(p => {
      const val = p.getFirstValue();
      return 'EXDATE:' + toISOString(val);
    }).filter(Boolean);
  }

  // ── Conversion VEVENT → Google Calendar event ──────────────────────────────

  function veventToGoogleEvent(vevent) {
    const event = {};
    const errors = [];

    // Champs texte
    const summary  = vevent.getFirstPropertyValue('summary');
    const desc     = vevent.getFirstPropertyValue('description');
    const location = vevent.getFirstPropertyValue('location');
    const uid      = vevent.getFirstPropertyValue('uid');

    if (summary)  event.summary     = summary;
    if (desc)     event.description = desc;
    if (location) event.location    = location;
    if (uid)      event.iCalUID     = uid;

    // Dates
    const dtstart = vevent.getFirstProperty('dtstart');
    const dtend   = vevent.getFirstProperty('dtend');

    if (!dtstart) {
      throw new Error('Événement sans DTSTART');
    }

    const startVal = dtstart.getFirstValue();
    const endVal   = dtend ? dtend.getFirstValue() : null;
    const isDate   = startVal.isDate;

    if (isDate) {
      event.start = { date: startVal.toString() };
      event.end   = endVal
        ? { date: endVal.toString() }
        : { date: startVal.toString() };
    } else {
      const tzid  = dtstart.getParameter('tzid') || 'UTC';
      const startISO = toISOString(startVal);
      event.start = { dateTime: startISO, timeZone: tzid };
      if (endVal) {
        event.end = { dateTime: toISOString(endVal), timeZone: tzid };
      } else {
        event.end = { ...event.start };
      }
    }

    // Récurrence
    const rrule = getRruleString(vevent);
    if (rrule) {
      event.recurrence = [rrule, ...getExdates(vevent)];
    }

    return event;
  }

  // ── Objet ParsedEvent ──────────────────────────────────────────────────────

  class ParsedEvent {
    constructor(vevent) {
      this.vevent = vevent;
      this.googleEvent = null;
      this.error = null;

      try {
        this.googleEvent = veventToGoogleEvent(vevent);
      } catch (e) {
        this.error = e.message;
      }
    }

    get isValid()    { return this.error === null; }
    get uid()        { return this.vevent.getFirstPropertyValue('uid') || null; }
    get summary()    { return this.vevent.getFirstPropertyValue('summary') || '(sans titre)'; }
    get isRecurring(){ return !!this.vevent.getFirstProperty('rrule'); }
    get location()   { return this.vevent.getFirstPropertyValue('location') || null; }

    get startDisplay() {
      const p = this.vevent.getFirstProperty('dtstart');
      return p ? formatDisplay(p.getFirstValue()) : '';
    }
    get endDisplay() {
      const p = this.vevent.getFirstProperty('dtend');
      return p ? formatDisplay(p.getFirstValue()) : '';
    }

    toPreviewObject() {
      return {
        uid:       this.uid,
        summary:   this.summary,
        start:     this.startDisplay,
        end:       this.endDisplay,
        recurring: this.isRecurring,
        location:  this.location,
        valid:     this.isValid,
        error:     this.error,
      };
    }
  }

  // ── Point d'entrée public ──────────────────────────────────────────────────

  /**
   * Parse le contenu texte d'un fichier ICS.
   * @param {string} icsText - Contenu brut du fichier ICS
   * @returns {ParsedEvent[]}
   */
  function parseICS(icsText) {
    const jcalData = ICAL.parse(icsText);
    const comp     = new ICAL.Component(jcalData);
    const vevents  = comp.getAllSubcomponents('vevent');
    return vevents.map(v => new ParsedEvent(v));
  }

  return { parseICS, ParsedEvent };
})();
