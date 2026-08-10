/**
 * js/parser.js
 * Parse les fichiers iCalendar (.ics) avec ical.js
 * et convertit les VEVENT en objets compatibles Google Calendar API.
 */

const ICSParser = (() => {

  // ── Fuseaux horaires ───────────────────────────────────────────────────────

  /**
   * Correspondance noms Windows → identifiants IANA (source : CLDR windowsZones).
   * Exchange / Outlook émettent des TZID comme « GMT Standard Time », que l'API
   * Google Calendar refuse ("Invalid time zone definition for start time").
   */
  const WINDOWS_TO_IANA = {
    'Dateline Standard Time': 'Etc/GMT+12',
    'UTC-11': 'Etc/GMT+11',
    'Aleutian Standard Time': 'America/Adak',
    'Hawaiian Standard Time': 'Pacific/Honolulu',
    'Marquesas Standard Time': 'Pacific/Marquesas',
    'Alaskan Standard Time': 'America/Anchorage',
    'UTC-09': 'Etc/GMT+9',
    'Pacific Standard Time (Mexico)': 'America/Tijuana',
    'UTC-08': 'Etc/GMT+8',
    'Pacific Standard Time': 'America/Los_Angeles',
    'US Mountain Standard Time': 'America/Phoenix',
    'Mountain Standard Time (Mexico)': 'America/Chihuahua',
    'Mountain Standard Time': 'America/Denver',
    'Yukon Standard Time': 'America/Whitehorse',
    'Central America Standard Time': 'America/Guatemala',
    'Central Standard Time': 'America/Chicago',
    'Easter Island Standard Time': 'Pacific/Easter',
    'Central Standard Time (Mexico)': 'America/Mexico_City',
    'Canada Central Standard Time': 'America/Regina',
    'SA Pacific Standard Time': 'America/Bogota',
    'Eastern Standard Time (Mexico)': 'America/Cancun',
    'Eastern Standard Time': 'America/New_York',
    'Haiti Standard Time': 'America/Port-au-Prince',
    'Cuba Standard Time': 'America/Havana',
    'US Eastern Standard Time': 'America/Indianapolis',
    'Turks And Caicos Standard Time': 'America/Grand_Turk',
    'Paraguay Standard Time': 'America/Asuncion',
    'Atlantic Standard Time': 'America/Halifax',
    'Venezuela Standard Time': 'America/Caracas',
    'Central Brazilian Standard Time': 'America/Cuiaba',
    'SA Western Standard Time': 'America/La_Paz',
    'Pacific SA Standard Time': 'America/Santiago',
    'Newfoundland Standard Time': 'America/St_Johns',
    'Tocantins Standard Time': 'America/Araguaina',
    'E. South America Standard Time': 'America/Sao_Paulo',
    'SA Eastern Standard Time': 'America/Cayenne',
    'Argentina Standard Time': 'America/Buenos_Aires',
    'Greenland Standard Time': 'America/Godthab',
    'Montevideo Standard Time': 'America/Montevideo',
    'Magallanes Standard Time': 'America/Punta_Arenas',
    'Saint Pierre Standard Time': 'America/Miquelon',
    'Bahia Standard Time': 'America/Bahia',
    'UTC-02': 'Etc/GMT+2',
    'Azores Standard Time': 'Atlantic/Azores',
    'Cape Verde Standard Time': 'Atlantic/Cape_Verde',
    'UTC': 'Etc/UTC',
    'GMT Standard Time': 'Europe/London',
    'Greenwich Standard Time': 'Atlantic/Reykjavik',
    'Sao Tome Standard Time': 'Africa/Sao_Tome',
    'Morocco Standard Time': 'Africa/Casablanca',
    'W. Europe Standard Time': 'Europe/Berlin',
    'Central Europe Standard Time': 'Europe/Budapest',
    'Romance Standard Time': 'Europe/Paris',
    'Central European Standard Time': 'Europe/Warsaw',
    'W. Central Africa Standard Time': 'Africa/Lagos',
    'Jordan Standard Time': 'Asia/Amman',
    'GTB Standard Time': 'Europe/Bucharest',
    'Middle East Standard Time': 'Asia/Beirut',
    'Egypt Standard Time': 'Africa/Cairo',
    'E. Europe Standard Time': 'Europe/Chisinau',
    'Syria Standard Time': 'Asia/Damascus',
    'West Bank Standard Time': 'Asia/Hebron',
    'South Africa Standard Time': 'Africa/Johannesburg',
    'FLE Standard Time': 'Europe/Kiev',
    'Israel Standard Time': 'Asia/Jerusalem',
    'Kaliningrad Standard Time': 'Europe/Kaliningrad',
    'Sudan Standard Time': 'Africa/Khartoum',
    'Libya Standard Time': 'Africa/Tripoli',
    'Namibia Standard Time': 'Africa/Windhoek',
    'Arabic Standard Time': 'Asia/Baghdad',
    'Turkey Standard Time': 'Europe/Istanbul',
    'Arab Standard Time': 'Asia/Riyadh',
    'Belarus Standard Time': 'Europe/Minsk',
    'Russian Standard Time': 'Europe/Moscow',
    'E. Africa Standard Time': 'Africa/Nairobi',
    'Iran Standard Time': 'Asia/Tehran',
    'Arabian Standard Time': 'Asia/Dubai',
    'Astrakhan Standard Time': 'Europe/Astrakhan',
    'Azerbaijan Standard Time': 'Asia/Baku',
    'Russia Time Zone 3': 'Europe/Samara',
    'Mauritius Standard Time': 'Indian/Mauritius',
    'Saratov Standard Time': 'Europe/Saratov',
    'Georgian Standard Time': 'Asia/Tbilisi',
    'Volgograd Standard Time': 'Europe/Volgograd',
    'Caucasus Standard Time': 'Asia/Yerevan',
    'Afghanistan Standard Time': 'Asia/Kabul',
    'West Asia Standard Time': 'Asia/Tashkent',
    'Ekaterinburg Standard Time': 'Asia/Yekaterinburg',
    'Pakistan Standard Time': 'Asia/Karachi',
    'Qyzylorda Standard Time': 'Asia/Qyzylorda',
    'India Standard Time': 'Asia/Calcutta',
    'Sri Lanka Standard Time': 'Asia/Colombo',
    'Nepal Standard Time': 'Asia/Katmandu',
    'Central Asia Standard Time': 'Asia/Almaty',
    'Bangladesh Standard Time': 'Asia/Dhaka',
    'Omsk Standard Time': 'Asia/Omsk',
    'Myanmar Standard Time': 'Asia/Rangoon',
    'SE Asia Standard Time': 'Asia/Bangkok',
    'Altai Standard Time': 'Asia/Barnaul',
    'W. Mongolia Standard Time': 'Asia/Hovd',
    'North Asia Standard Time': 'Asia/Krasnoyarsk',
    'N. Central Asia Standard Time': 'Asia/Novosibirsk',
    'Tomsk Standard Time': 'Asia/Tomsk',
    'China Standard Time': 'Asia/Shanghai',
    'North Asia East Standard Time': 'Asia/Irkutsk',
    'Singapore Standard Time': 'Asia/Singapore',
    'W. Australia Standard Time': 'Australia/Perth',
    'Taipei Standard Time': 'Asia/Taipei',
    'Ulaanbaatar Standard Time': 'Asia/Ulaanbaatar',
    'Aus Central W. Standard Time': 'Australia/Eucla',
    'Transbaikal Standard Time': 'Asia/Chita',
    'Tokyo Standard Time': 'Asia/Tokyo',
    'North Korea Standard Time': 'Asia/Pyongyang',
    'Korea Standard Time': 'Asia/Seoul',
    'Yakutsk Standard Time': 'Asia/Yakutsk',
    'Cen. Australia Standard Time': 'Australia/Adelaide',
    'AUS Central Standard Time': 'Australia/Darwin',
    'E. Australia Standard Time': 'Australia/Brisbane',
    'AUS Eastern Standard Time': 'Australia/Sydney',
    'West Pacific Standard Time': 'Pacific/Port_Moresby',
    'Tasmania Standard Time': 'Australia/Hobart',
    'Vladivostok Standard Time': 'Asia/Vladivostok',
    'Lord Howe Standard Time': 'Australia/Lord_Howe',
    'Bougainville Standard Time': 'Pacific/Bougainville',
    'Russia Time Zone 10': 'Asia/Srednekolymsk',
    'Magadan Standard Time': 'Asia/Magadan',
    'Norfolk Standard Time': 'Pacific/Norfolk',
    'Sakhalin Standard Time': 'Asia/Sakhalin',
    'Central Pacific Standard Time': 'Pacific/Guadalcanal',
    'Russia Time Zone 11': 'Asia/Kamchatka',
    'New Zealand Standard Time': 'Pacific/Auckland',
    'UTC+12': 'Etc/GMT-12',
    'Fiji Standard Time': 'Pacific/Fiji',
    'Chatham Islands Standard Time': 'Pacific/Chatham',
    'UTC+13': 'Etc/GMT-13',
    'Tonga Standard Time': 'Pacific/Tongatapu',
    'Samoa Standard Time': 'Pacific/Apia',
    'Line Islands Standard Time': 'Pacific/Kiritimati',
  };

  /** Un identifiant est-il connu du moteur de fuseaux du navigateur ? */
  function isIanaZone(tzid) {
    try {
      new Intl.DateTimeFormat('en-US', { timeZone: tzid });
      return true;
    } catch (e) {
      return false;
    }
  }

  /**
   * Normalise un TZID de fichier ICS en identifiant accepté par Google Calendar.
   * @returns {string|null} identifiant IANA, ou null si non résoluble
   */
  function normalizeTimeZone(tzid) {
    if (!tzid) return null;
    // Certains producteurs préfixent le TZID (ex. « /mozilla.org/…/Europe/Paris »)
    const cleaned = String(tzid).replace(/^\/+[^/]*\/[^/]*\//, '').trim();
    if (WINDOWS_TO_IANA[cleaned]) return WINDOWS_TO_IANA[cleaned];
    if (isIanaZone(cleaned)) return cleaned;
    return null;
  }

  /**
   * Déclare les VTIMEZONE du fichier auprès d'ical.js.
   * Sans cela, un TZID inconnu (« GMT Standard Time ») est traité comme une heure
   * flottante, donc interprétée dans le fuseau du navigateur : l'instant importé
   * est décalé.
   */
  function registerTimezones(comp) {
    // Repart d'un service vierge (Z/UTC/GMT seuls) : les définitions d'un fichier
    // précédemment importé ne doivent pas déteindre sur celui-ci.
    ICAL.TimezoneService.reset();
    comp.getAllSubcomponents('vtimezone').forEach(vtz => {
      try {
        ICAL.TimezoneService.register(vtz);
      } catch (e) {
        // VTIMEZONE illisible : on continue, `toDate()` rattrapera via le TZID
      }
    });
  }

  /** Décalage d'un fuseau IANA, en millisecondes, à un instant donné. */
  function zoneOffset(timestamp, ianaZone) {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: ianaZone, hour12: false,
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    }).formatToParts(timestamp).reduce((acc, p) => (acc[p.type] = p.value, acc), {});
    const asUTC = Date.UTC(
      Number(parts.year), Number(parts.month) - 1, Number(parts.day),
      Number(parts.hour) % 24, Number(parts.minute), Number(parts.second)
    );
    return asUTC - timestamp;
  }

  /** Interprète une heure « murale » dans un fuseau IANA et renvoie l'instant réel. */
  function wallClockToDate(jcalDate, ianaZone) {
    const wall = Date.UTC(
      jcalDate.year, jcalDate.month - 1, jcalDate.day,
      jcalDate.hour, jcalDate.minute, jcalDate.second
    );
    // Deux passes : la première estime le décalage, la seconde le corrige aux
    // changements d'heure (le décalage dépend de l'instant qu'on cherche).
    const offset = zoneOffset(wall - zoneOffset(wall, ianaZone), ianaZone);
    return new Date(wall - offset);
  }

  // ── Helpers ────────────────────────────────────────────────────────────────

  /**
   * Instant absolu d'une propriété date-heure.
   * ical.js ne résout un TZID que si le fichier fournit le VTIMEZONE correspondant ;
   * sinon la valeur est « flottante », donc lue dans le fuseau du navigateur. Si le
   * TZID est malgré tout un fuseau connu, on l'applique nous-mêmes.
   */
  function toDate(jcalDate, prop) {
    if (!jcalDate) return null;
    const isFloating = !jcalDate.isDate && jcalDate.zone && jcalDate.zone.tzid === 'floating';
    if (isFloating) {
      const zone = normalizeTimeZone(prop && prop.getParameter('tzid'));
      if (zone) return wallClockToDate(jcalDate, zone);
    }
    return jcalDate.toJSDate();
  }

  function toISOString(jcalDate, prop) {
    const dt = toDate(jcalDate, prop);
    return dt ? dt.toISOString() : null;
  }

  function formatDisplay(jcalDate, prop) {
    const dt = toDate(jcalDate, prop);
    if (!dt) return '';
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

  /** Instant → forme iCalendar UTC (« 20260810T120000Z »), seule acceptée par Google. */
  function toICSDateTime(date) {
    return date.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
  }

  function getExdates(vevent) {
    return vevent.getAllProperties('exdate').map(p => {
      const values = p.getValues();
      if (!values.length) return null;
      // Une EXDATE en date seule doit rester en date seule, sans conversion UTC.
      if (values[0].isDate) {
        return 'EXDATE;VALUE=DATE:' + values.map(v => v.toString().replace(/-/g, '')).join(',');
      }
      return 'EXDATE:' + values.map(v => toICSDateTime(toDate(v, p))).join(',');
    }).filter(Boolean);
  }

  /**
   * Fuseau à transmettre à Google pour une propriété date-heure.
   * Faute de TZID exploitable, une valeur en UTC (« …Z ») reste annoncée comme
   * telle ; une heure flottante n'annonce rien, l'agenda de destination fait foi.
   */
  function zoneOf(prop, value) {
    const fromTzid = normalizeTimeZone(prop.getParameter('tzid'));
    if (fromTzid) return fromTzid;
    return (value && value.zone && value.zone.tzid === 'UTC') ? 'UTC' : null;
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
      // `dateTime` est déjà un instant absolu (suffixe Z) : `timeZone` ne sert
      // qu'à la récurrence et à l'affichage. Un TZID non résoluble est donc omis
      // plutôt que transmis tel quel — Google rejette les noms inconnus.
      const startZone = zoneOf(dtstart, startVal);
      const endZone   = dtend ? zoneOf(dtend, endVal) : null;

      event.start = { dateTime: toISOString(startVal, dtstart) };
      if (startZone) event.start.timeZone = startZone;

      if (endVal) {
        event.end = { dateTime: toISOString(endVal, dtend) };
        const zone = endZone || startZone;
        if (zone) event.end.timeZone = zone;
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
      return p ? formatDisplay(p.getFirstValue(), p) : '';
    }
    get endDisplay() {
      const p = this.vevent.getFirstProperty('dtend');
      return p ? formatDisplay(p.getFirstValue(), p) : '';
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
    // Avant toute lecture de date : les valeurs sont résolues au premier accès.
    registerTimezones(comp);
    const vevents  = comp.getAllSubcomponents('vevent');
    return vevents.map(v => new ParsedEvent(v));
  }

  return { parseICS, ParsedEvent };
})();
