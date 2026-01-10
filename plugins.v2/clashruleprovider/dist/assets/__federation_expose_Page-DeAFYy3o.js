import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { V as VAceEditor, c as commonjsGlobal, g as getDefaultExportFromCjs } from './theme-monokai-CF_yROe-.js';
import { i as isSystemRule, t as timestampToDate, g as getRuleTypeColor, a as getActionColor, _ as _export_sfc, p as pageTitle, b as isManual, c as isRegion, d as getSourceColor, e as getProxyGroupTypeColor, f as isValidUrl, h as isInvalid, j as getProxyColor, k as extractDomain, l as formatTimestamp, m as getExpireColor, n as formatBytes, o as getUsageColor, q as getUsedPercentageFloor, r as getFormatColor, s as getBehaviorColor, u as getBoolColor, v as validateIPs } from './_plugin-vue_export-helper-D32QZFxh.js';
import { M as MetaLogo } from './Meta-1zu2nKV2.js';

/*! js-yaml 4.1.1 https://github.com/nodeca/js-yaml @license MIT */
function isNothing(subject) {
  return (typeof subject === 'undefined') || (subject === null);
}


function isObject$1(subject) {
  return (typeof subject === 'object') && (subject !== null);
}


function toArray(sequence) {
  if (Array.isArray(sequence)) return sequence;
  else if (isNothing(sequence)) return [];

  return [ sequence ];
}


function extend(target, source) {
  var index, length, key, sourceKeys;

  if (source) {
    sourceKeys = Object.keys(source);

    for (index = 0, length = sourceKeys.length; index < length; index += 1) {
      key = sourceKeys[index];
      target[key] = source[key];
    }
  }

  return target;
}


function repeat(string, count) {
  var result = '', cycle;

  for (cycle = 0; cycle < count; cycle += 1) {
    result += string;
  }

  return result;
}


function isNegativeZero(number) {
  return (number === 0) && (Number.NEGATIVE_INFINITY === 1 / number);
}


var isNothing_1      = isNothing;
var isObject_1       = isObject$1;
var toArray_1        = toArray;
var repeat_1         = repeat;
var isNegativeZero_1 = isNegativeZero;
var extend_1         = extend;

var common = {
	isNothing: isNothing_1,
	isObject: isObject_1,
	toArray: toArray_1,
	repeat: repeat_1,
	isNegativeZero: isNegativeZero_1,
	extend: extend_1
};

// YAML error class. http://stackoverflow.com/questions/8458984


function formatError(exception, compact) {
  var where = '', message = exception.reason || '(unknown reason)';

  if (!exception.mark) return message;

  if (exception.mark.name) {
    where += 'in "' + exception.mark.name + '" ';
  }

  where += '(' + (exception.mark.line + 1) + ':' + (exception.mark.column + 1) + ')';

  if (!compact && exception.mark.snippet) {
    where += '\n\n' + exception.mark.snippet;
  }

  return message + ' ' + where;
}


function YAMLException$1(reason, mark) {
  // Super constructor
  Error.call(this);

  this.name = 'YAMLException';
  this.reason = reason;
  this.mark = mark;
  this.message = formatError(this, false);

  // Include stack trace in error object
  if (Error.captureStackTrace) {
    // Chrome and NodeJS
    Error.captureStackTrace(this, this.constructor);
  } else {
    // FF, IE 10+ and Safari 6+. Fallback for others
    this.stack = (new Error()).stack || '';
  }
}


// Inherit from Error
YAMLException$1.prototype = Object.create(Error.prototype);
YAMLException$1.prototype.constructor = YAMLException$1;


YAMLException$1.prototype.toString = function toString(compact) {
  return this.name + ': ' + formatError(this, compact);
};


var exception = YAMLException$1;

// get snippet for a single line, respecting maxLength
function getLine(buffer, lineStart, lineEnd, position, maxLineLength) {
  var head = '';
  var tail = '';
  var maxHalfLength = Math.floor(maxLineLength / 2) - 1;

  if (position - lineStart > maxHalfLength) {
    head = ' ... ';
    lineStart = position - maxHalfLength + head.length;
  }

  if (lineEnd - position > maxHalfLength) {
    tail = ' ...';
    lineEnd = position + maxHalfLength - tail.length;
  }

  return {
    str: head + buffer.slice(lineStart, lineEnd).replace(/\t/g, '→') + tail,
    pos: position - lineStart + head.length // relative position
  };
}


function padStart(string, max) {
  return common.repeat(' ', max - string.length) + string;
}


function makeSnippet(mark, options) {
  options = Object.create(options || null);

  if (!mark.buffer) return null;

  if (!options.maxLength) options.maxLength = 79;
  if (typeof options.indent      !== 'number') options.indent      = 1;
  if (typeof options.linesBefore !== 'number') options.linesBefore = 3;
  if (typeof options.linesAfter  !== 'number') options.linesAfter  = 2;

  var re = /\r?\n|\r|\0/g;
  var lineStarts = [ 0 ];
  var lineEnds = [];
  var match;
  var foundLineNo = -1;

  while ((match = re.exec(mark.buffer))) {
    lineEnds.push(match.index);
    lineStarts.push(match.index + match[0].length);

    if (mark.position <= match.index && foundLineNo < 0) {
      foundLineNo = lineStarts.length - 2;
    }
  }

  if (foundLineNo < 0) foundLineNo = lineStarts.length - 1;

  var result = '', i, line;
  var lineNoLength = Math.min(mark.line + options.linesAfter, lineEnds.length).toString().length;
  var maxLineLength = options.maxLength - (options.indent + lineNoLength + 3);

  for (i = 1; i <= options.linesBefore; i++) {
    if (foundLineNo - i < 0) break;
    line = getLine(
      mark.buffer,
      lineStarts[foundLineNo - i],
      lineEnds[foundLineNo - i],
      mark.position - (lineStarts[foundLineNo] - lineStarts[foundLineNo - i]),
      maxLineLength
    );
    result = common.repeat(' ', options.indent) + padStart((mark.line - i + 1).toString(), lineNoLength) +
      ' | ' + line.str + '\n' + result;
  }

  line = getLine(mark.buffer, lineStarts[foundLineNo], lineEnds[foundLineNo], mark.position, maxLineLength);
  result += common.repeat(' ', options.indent) + padStart((mark.line + 1).toString(), lineNoLength) +
    ' | ' + line.str + '\n';
  result += common.repeat('-', options.indent + lineNoLength + 3 + line.pos) + '^' + '\n';

  for (i = 1; i <= options.linesAfter; i++) {
    if (foundLineNo + i >= lineEnds.length) break;
    line = getLine(
      mark.buffer,
      lineStarts[foundLineNo + i],
      lineEnds[foundLineNo + i],
      mark.position - (lineStarts[foundLineNo] - lineStarts[foundLineNo + i]),
      maxLineLength
    );
    result += common.repeat(' ', options.indent) + padStart((mark.line + i + 1).toString(), lineNoLength) +
      ' | ' + line.str + '\n';
  }

  return result.replace(/\n$/, '');
}


var snippet = makeSnippet;

var TYPE_CONSTRUCTOR_OPTIONS = [
  'kind',
  'multi',
  'resolve',
  'construct',
  'instanceOf',
  'predicate',
  'represent',
  'representName',
  'defaultStyle',
  'styleAliases'
];

var YAML_NODE_KINDS = [
  'scalar',
  'sequence',
  'mapping'
];

function compileStyleAliases(map) {
  var result = {};

  if (map !== null) {
    Object.keys(map).forEach(function (style) {
      map[style].forEach(function (alias) {
        result[String(alias)] = style;
      });
    });
  }

  return result;
}

function Type$1(tag, options) {
  options = options || {};

  Object.keys(options).forEach(function (name) {
    if (TYPE_CONSTRUCTOR_OPTIONS.indexOf(name) === -1) {
      throw new exception('Unknown option "' + name + '" is met in definition of "' + tag + '" YAML type.');
    }
  });

  // TODO: Add tag format check.
  this.options       = options; // keep original options in case user wants to extend this type later
  this.tag           = tag;
  this.kind          = options['kind']          || null;
  this.resolve       = options['resolve']       || function () { return true; };
  this.construct     = options['construct']     || function (data) { return data; };
  this.instanceOf    = options['instanceOf']    || null;
  this.predicate     = options['predicate']     || null;
  this.represent     = options['represent']     || null;
  this.representName = options['representName'] || null;
  this.defaultStyle  = options['defaultStyle']  || null;
  this.multi         = options['multi']         || false;
  this.styleAliases  = compileStyleAliases(options['styleAliases'] || null);

  if (YAML_NODE_KINDS.indexOf(this.kind) === -1) {
    throw new exception('Unknown kind "' + this.kind + '" is specified for "' + tag + '" YAML type.');
  }
}

var type = Type$1;

/*eslint-disable max-len*/





function compileList(schema, name) {
  var result = [];

  schema[name].forEach(function (currentType) {
    var newIndex = result.length;

    result.forEach(function (previousType, previousIndex) {
      if (previousType.tag === currentType.tag &&
          previousType.kind === currentType.kind &&
          previousType.multi === currentType.multi) {

        newIndex = previousIndex;
      }
    });

    result[newIndex] = currentType;
  });

  return result;
}


function compileMap(/* lists... */) {
  var result = {
        scalar: {},
        sequence: {},
        mapping: {},
        fallback: {},
        multi: {
          scalar: [],
          sequence: [],
          mapping: [],
          fallback: []
        }
      }, index, length;

  function collectType(type) {
    if (type.multi) {
      result.multi[type.kind].push(type);
      result.multi['fallback'].push(type);
    } else {
      result[type.kind][type.tag] = result['fallback'][type.tag] = type;
    }
  }

  for (index = 0, length = arguments.length; index < length; index += 1) {
    arguments[index].forEach(collectType);
  }
  return result;
}


function Schema$1(definition) {
  return this.extend(definition);
}


Schema$1.prototype.extend = function extend(definition) {
  var implicit = [];
  var explicit = [];

  if (definition instanceof type) {
    // Schema.extend(type)
    explicit.push(definition);

  } else if (Array.isArray(definition)) {
    // Schema.extend([ type1, type2, ... ])
    explicit = explicit.concat(definition);

  } else if (definition && (Array.isArray(definition.implicit) || Array.isArray(definition.explicit))) {
    // Schema.extend({ explicit: [ type1, type2, ... ], implicit: [ type1, type2, ... ] })
    if (definition.implicit) implicit = implicit.concat(definition.implicit);
    if (definition.explicit) explicit = explicit.concat(definition.explicit);

  } else {
    throw new exception('Schema.extend argument should be a Type, [ Type ], ' +
      'or a schema definition ({ implicit: [...], explicit: [...] })');
  }

  implicit.forEach(function (type$1) {
    if (!(type$1 instanceof type)) {
      throw new exception('Specified list of YAML types (or a single Type object) contains a non-Type object.');
    }

    if (type$1.loadKind && type$1.loadKind !== 'scalar') {
      throw new exception('There is a non-scalar type in the implicit list of a schema. Implicit resolving of such types is not supported.');
    }

    if (type$1.multi) {
      throw new exception('There is a multi type in the implicit list of a schema. Multi tags can only be listed as explicit.');
    }
  });

  explicit.forEach(function (type$1) {
    if (!(type$1 instanceof type)) {
      throw new exception('Specified list of YAML types (or a single Type object) contains a non-Type object.');
    }
  });

  var result = Object.create(Schema$1.prototype);

  result.implicit = (this.implicit || []).concat(implicit);
  result.explicit = (this.explicit || []).concat(explicit);

  result.compiledImplicit = compileList(result, 'implicit');
  result.compiledExplicit = compileList(result, 'explicit');
  result.compiledTypeMap  = compileMap(result.compiledImplicit, result.compiledExplicit);

  return result;
};


var schema = Schema$1;

var str = new type('tag:yaml.org,2002:str', {
  kind: 'scalar',
  construct: function (data) { return data !== null ? data : ''; }
});

var seq = new type('tag:yaml.org,2002:seq', {
  kind: 'sequence',
  construct: function (data) { return data !== null ? data : []; }
});

var map = new type('tag:yaml.org,2002:map', {
  kind: 'mapping',
  construct: function (data) { return data !== null ? data : {}; }
});

var failsafe = new schema({
  explicit: [
    str,
    seq,
    map
  ]
});

function resolveYamlNull(data) {
  if (data === null) return true;

  var max = data.length;

  return (max === 1 && data === '~') ||
         (max === 4 && (data === 'null' || data === 'Null' || data === 'NULL'));
}

function constructYamlNull() {
  return null;
}

function isNull(object) {
  return object === null;
}

var _null = new type('tag:yaml.org,2002:null', {
  kind: 'scalar',
  resolve: resolveYamlNull,
  construct: constructYamlNull,
  predicate: isNull,
  represent: {
    canonical: function () { return '~';    },
    lowercase: function () { return 'null'; },
    uppercase: function () { return 'NULL'; },
    camelcase: function () { return 'Null'; },
    empty:     function () { return '';     }
  },
  defaultStyle: 'lowercase'
});

function resolveYamlBoolean(data) {
  if (data === null) return false;

  var max = data.length;

  return (max === 4 && (data === 'true' || data === 'True' || data === 'TRUE')) ||
         (max === 5 && (data === 'false' || data === 'False' || data === 'FALSE'));
}

function constructYamlBoolean(data) {
  return data === 'true' ||
         data === 'True' ||
         data === 'TRUE';
}

function isBoolean(object) {
  return Object.prototype.toString.call(object) === '[object Boolean]';
}

var bool = new type('tag:yaml.org,2002:bool', {
  kind: 'scalar',
  resolve: resolveYamlBoolean,
  construct: constructYamlBoolean,
  predicate: isBoolean,
  represent: {
    lowercase: function (object) { return object ? 'true' : 'false'; },
    uppercase: function (object) { return object ? 'TRUE' : 'FALSE'; },
    camelcase: function (object) { return object ? 'True' : 'False'; }
  },
  defaultStyle: 'lowercase'
});

function isHexCode(c) {
  return ((0x30/* 0 */ <= c) && (c <= 0x39/* 9 */)) ||
         ((0x41/* A */ <= c) && (c <= 0x46/* F */)) ||
         ((0x61/* a */ <= c) && (c <= 0x66/* f */));
}

function isOctCode(c) {
  return ((0x30/* 0 */ <= c) && (c <= 0x37/* 7 */));
}

function isDecCode(c) {
  return ((0x30/* 0 */ <= c) && (c <= 0x39/* 9 */));
}

function resolveYamlInteger(data) {
  if (data === null) return false;

  var max = data.length,
      index = 0,
      hasDigits = false,
      ch;

  if (!max) return false;

  ch = data[index];

  // sign
  if (ch === '-' || ch === '+') {
    ch = data[++index];
  }

  if (ch === '0') {
    // 0
    if (index + 1 === max) return true;
    ch = data[++index];

    // base 2, base 8, base 16

    if (ch === 'b') {
      // base 2
      index++;

      for (; index < max; index++) {
        ch = data[index];
        if (ch === '_') continue;
        if (ch !== '0' && ch !== '1') return false;
        hasDigits = true;
      }
      return hasDigits && ch !== '_';
    }


    if (ch === 'x') {
      // base 16
      index++;

      for (; index < max; index++) {
        ch = data[index];
        if (ch === '_') continue;
        if (!isHexCode(data.charCodeAt(index))) return false;
        hasDigits = true;
      }
      return hasDigits && ch !== '_';
    }


    if (ch === 'o') {
      // base 8
      index++;

      for (; index < max; index++) {
        ch = data[index];
        if (ch === '_') continue;
        if (!isOctCode(data.charCodeAt(index))) return false;
        hasDigits = true;
      }
      return hasDigits && ch !== '_';
    }
  }

  // base 10 (except 0)

  // value should not start with `_`;
  if (ch === '_') return false;

  for (; index < max; index++) {
    ch = data[index];
    if (ch === '_') continue;
    if (!isDecCode(data.charCodeAt(index))) {
      return false;
    }
    hasDigits = true;
  }

  // Should have digits and should not end with `_`
  if (!hasDigits || ch === '_') return false;

  return true;
}

function constructYamlInteger(data) {
  var value = data, sign = 1, ch;

  if (value.indexOf('_') !== -1) {
    value = value.replace(/_/g, '');
  }

  ch = value[0];

  if (ch === '-' || ch === '+') {
    if (ch === '-') sign = -1;
    value = value.slice(1);
    ch = value[0];
  }

  if (value === '0') return 0;

  if (ch === '0') {
    if (value[1] === 'b') return sign * parseInt(value.slice(2), 2);
    if (value[1] === 'x') return sign * parseInt(value.slice(2), 16);
    if (value[1] === 'o') return sign * parseInt(value.slice(2), 8);
  }

  return sign * parseInt(value, 10);
}

function isInteger(object) {
  return (Object.prototype.toString.call(object)) === '[object Number]' &&
         (object % 1 === 0 && !common.isNegativeZero(object));
}

var int = new type('tag:yaml.org,2002:int', {
  kind: 'scalar',
  resolve: resolveYamlInteger,
  construct: constructYamlInteger,
  predicate: isInteger,
  represent: {
    binary:      function (obj) { return obj >= 0 ? '0b' + obj.toString(2) : '-0b' + obj.toString(2).slice(1); },
    octal:       function (obj) { return obj >= 0 ? '0o'  + obj.toString(8) : '-0o'  + obj.toString(8).slice(1); },
    decimal:     function (obj) { return obj.toString(10); },
    /* eslint-disable max-len */
    hexadecimal: function (obj) { return obj >= 0 ? '0x' + obj.toString(16).toUpperCase() :  '-0x' + obj.toString(16).toUpperCase().slice(1); }
  },
  defaultStyle: 'decimal',
  styleAliases: {
    binary:      [ 2,  'bin' ],
    octal:       [ 8,  'oct' ],
    decimal:     [ 10, 'dec' ],
    hexadecimal: [ 16, 'hex' ]
  }
});

var YAML_FLOAT_PATTERN = new RegExp(
  // 2.5e4, 2.5 and integers
  '^(?:[-+]?(?:[0-9][0-9_]*)(?:\\.[0-9_]*)?(?:[eE][-+]?[0-9]+)?' +
  // .2e4, .2
  // special case, seems not from spec
  '|\\.[0-9_]+(?:[eE][-+]?[0-9]+)?' +
  // .inf
  '|[-+]?\\.(?:inf|Inf|INF)' +
  // .nan
  '|\\.(?:nan|NaN|NAN))$');

function resolveYamlFloat(data) {
  if (data === null) return false;

  if (!YAML_FLOAT_PATTERN.test(data) ||
      // Quick hack to not allow integers end with `_`
      // Probably should update regexp & check speed
      data[data.length - 1] === '_') {
    return false;
  }

  return true;
}

function constructYamlFloat(data) {
  var value, sign;

  value  = data.replace(/_/g, '').toLowerCase();
  sign   = value[0] === '-' ? -1 : 1;

  if ('+-'.indexOf(value[0]) >= 0) {
    value = value.slice(1);
  }

  if (value === '.inf') {
    return (sign === 1) ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY;

  } else if (value === '.nan') {
    return NaN;
  }
  return sign * parseFloat(value, 10);
}


var SCIENTIFIC_WITHOUT_DOT = /^[-+]?[0-9]+e/;

function representYamlFloat(object, style) {
  var res;

  if (isNaN(object)) {
    switch (style) {
      case 'lowercase': return '.nan';
      case 'uppercase': return '.NAN';
      case 'camelcase': return '.NaN';
    }
  } else if (Number.POSITIVE_INFINITY === object) {
    switch (style) {
      case 'lowercase': return '.inf';
      case 'uppercase': return '.INF';
      case 'camelcase': return '.Inf';
    }
  } else if (Number.NEGATIVE_INFINITY === object) {
    switch (style) {
      case 'lowercase': return '-.inf';
      case 'uppercase': return '-.INF';
      case 'camelcase': return '-.Inf';
    }
  } else if (common.isNegativeZero(object)) {
    return '-0.0';
  }

  res = object.toString(10);

  // JS stringifier can build scientific format without dots: 5e-100,
  // while YAML requres dot: 5.e-100. Fix it with simple hack

  return SCIENTIFIC_WITHOUT_DOT.test(res) ? res.replace('e', '.e') : res;
}

function isFloat(object) {
  return (Object.prototype.toString.call(object) === '[object Number]') &&
         (object % 1 !== 0 || common.isNegativeZero(object));
}

var float = new type('tag:yaml.org,2002:float', {
  kind: 'scalar',
  resolve: resolveYamlFloat,
  construct: constructYamlFloat,
  predicate: isFloat,
  represent: representYamlFloat,
  defaultStyle: 'lowercase'
});

var json = failsafe.extend({
  implicit: [
    _null,
    bool,
    int,
    float
  ]
});

var core = json;

var YAML_DATE_REGEXP = new RegExp(
  '^([0-9][0-9][0-9][0-9])'          + // [1] year
  '-([0-9][0-9])'                    + // [2] month
  '-([0-9][0-9])$');                   // [3] day

var YAML_TIMESTAMP_REGEXP = new RegExp(
  '^([0-9][0-9][0-9][0-9])'          + // [1] year
  '-([0-9][0-9]?)'                   + // [2] month
  '-([0-9][0-9]?)'                   + // [3] day
  '(?:[Tt]|[ \\t]+)'                 + // ...
  '([0-9][0-9]?)'                    + // [4] hour
  ':([0-9][0-9])'                    + // [5] minute
  ':([0-9][0-9])'                    + // [6] second
  '(?:\\.([0-9]*))?'                 + // [7] fraction
  '(?:[ \\t]*(Z|([-+])([0-9][0-9]?)' + // [8] tz [9] tz_sign [10] tz_hour
  '(?::([0-9][0-9]))?))?$');           // [11] tz_minute

function resolveYamlTimestamp(data) {
  if (data === null) return false;
  if (YAML_DATE_REGEXP.exec(data) !== null) return true;
  if (YAML_TIMESTAMP_REGEXP.exec(data) !== null) return true;
  return false;
}

function constructYamlTimestamp(data) {
  var match, year, month, day, hour, minute, second, fraction = 0,
      delta = null, tz_hour, tz_minute, date;

  match = YAML_DATE_REGEXP.exec(data);
  if (match === null) match = YAML_TIMESTAMP_REGEXP.exec(data);

  if (match === null) throw new Error('Date resolve error');

  // match: [1] year [2] month [3] day

  year = +(match[1]);
  month = +(match[2]) - 1; // JS month starts with 0
  day = +(match[3]);

  if (!match[4]) { // no hour
    return new Date(Date.UTC(year, month, day));
  }

  // match: [4] hour [5] minute [6] second [7] fraction

  hour = +(match[4]);
  minute = +(match[5]);
  second = +(match[6]);

  if (match[7]) {
    fraction = match[7].slice(0, 3);
    while (fraction.length < 3) { // milli-seconds
      fraction += '0';
    }
    fraction = +fraction;
  }

  // match: [8] tz [9] tz_sign [10] tz_hour [11] tz_minute

  if (match[9]) {
    tz_hour = +(match[10]);
    tz_minute = +(match[11] || 0);
    delta = (tz_hour * 60 + tz_minute) * 60000; // delta in mili-seconds
    if (match[9] === '-') delta = -delta;
  }

  date = new Date(Date.UTC(year, month, day, hour, minute, second, fraction));

  if (delta) date.setTime(date.getTime() - delta);

  return date;
}

function representYamlTimestamp(object /*, style*/) {
  return object.toISOString();
}

var timestamp = new type('tag:yaml.org,2002:timestamp', {
  kind: 'scalar',
  resolve: resolveYamlTimestamp,
  construct: constructYamlTimestamp,
  instanceOf: Date,
  represent: representYamlTimestamp
});

function resolveYamlMerge(data) {
  return data === '<<' || data === null;
}

var merge = new type('tag:yaml.org,2002:merge', {
  kind: 'scalar',
  resolve: resolveYamlMerge
});

/*eslint-disable no-bitwise*/





// [ 64, 65, 66 ] -> [ padding, CR, LF ]
var BASE64_MAP = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r';


function resolveYamlBinary(data) {
  if (data === null) return false;

  var code, idx, bitlen = 0, max = data.length, map = BASE64_MAP;

  // Convert one by one.
  for (idx = 0; idx < max; idx++) {
    code = map.indexOf(data.charAt(idx));

    // Skip CR/LF
    if (code > 64) continue;

    // Fail on illegal characters
    if (code < 0) return false;

    bitlen += 6;
  }

  // If there are any bits left, source was corrupted
  return (bitlen % 8) === 0;
}

function constructYamlBinary(data) {
  var idx, tailbits,
      input = data.replace(/[\r\n=]/g, ''), // remove CR/LF & padding to simplify scan
      max = input.length,
      map = BASE64_MAP,
      bits = 0,
      result = [];

  // Collect by 6*4 bits (3 bytes)

  for (idx = 0; idx < max; idx++) {
    if ((idx % 4 === 0) && idx) {
      result.push((bits >> 16) & 0xFF);
      result.push((bits >> 8) & 0xFF);
      result.push(bits & 0xFF);
    }

    bits = (bits << 6) | map.indexOf(input.charAt(idx));
  }

  // Dump tail

  tailbits = (max % 4) * 6;

  if (tailbits === 0) {
    result.push((bits >> 16) & 0xFF);
    result.push((bits >> 8) & 0xFF);
    result.push(bits & 0xFF);
  } else if (tailbits === 18) {
    result.push((bits >> 10) & 0xFF);
    result.push((bits >> 2) & 0xFF);
  } else if (tailbits === 12) {
    result.push((bits >> 4) & 0xFF);
  }

  return new Uint8Array(result);
}

function representYamlBinary(object /*, style*/) {
  var result = '', bits = 0, idx, tail,
      max = object.length,
      map = BASE64_MAP;

  // Convert every three bytes to 4 ASCII characters.

  for (idx = 0; idx < max; idx++) {
    if ((idx % 3 === 0) && idx) {
      result += map[(bits >> 18) & 0x3F];
      result += map[(bits >> 12) & 0x3F];
      result += map[(bits >> 6) & 0x3F];
      result += map[bits & 0x3F];
    }

    bits = (bits << 8) + object[idx];
  }

  // Dump tail

  tail = max % 3;

  if (tail === 0) {
    result += map[(bits >> 18) & 0x3F];
    result += map[(bits >> 12) & 0x3F];
    result += map[(bits >> 6) & 0x3F];
    result += map[bits & 0x3F];
  } else if (tail === 2) {
    result += map[(bits >> 10) & 0x3F];
    result += map[(bits >> 4) & 0x3F];
    result += map[(bits << 2) & 0x3F];
    result += map[64];
  } else if (tail === 1) {
    result += map[(bits >> 2) & 0x3F];
    result += map[(bits << 4) & 0x3F];
    result += map[64];
    result += map[64];
  }

  return result;
}

function isBinary(obj) {
  return Object.prototype.toString.call(obj) ===  '[object Uint8Array]';
}

var binary = new type('tag:yaml.org,2002:binary', {
  kind: 'scalar',
  resolve: resolveYamlBinary,
  construct: constructYamlBinary,
  predicate: isBinary,
  represent: representYamlBinary
});

var _hasOwnProperty$3 = Object.prototype.hasOwnProperty;
var _toString$2       = Object.prototype.toString;

function resolveYamlOmap(data) {
  if (data === null) return true;

  var objectKeys = [], index, length, pair, pairKey, pairHasKey,
      object = data;

  for (index = 0, length = object.length; index < length; index += 1) {
    pair = object[index];
    pairHasKey = false;

    if (_toString$2.call(pair) !== '[object Object]') return false;

    for (pairKey in pair) {
      if (_hasOwnProperty$3.call(pair, pairKey)) {
        if (!pairHasKey) pairHasKey = true;
        else return false;
      }
    }

    if (!pairHasKey) return false;

    if (objectKeys.indexOf(pairKey) === -1) objectKeys.push(pairKey);
    else return false;
  }

  return true;
}

function constructYamlOmap(data) {
  return data !== null ? data : [];
}

var omap = new type('tag:yaml.org,2002:omap', {
  kind: 'sequence',
  resolve: resolveYamlOmap,
  construct: constructYamlOmap
});

var _toString$1 = Object.prototype.toString;

function resolveYamlPairs(data) {
  if (data === null) return true;

  var index, length, pair, keys, result,
      object = data;

  result = new Array(object.length);

  for (index = 0, length = object.length; index < length; index += 1) {
    pair = object[index];

    if (_toString$1.call(pair) !== '[object Object]') return false;

    keys = Object.keys(pair);

    if (keys.length !== 1) return false;

    result[index] = [ keys[0], pair[keys[0]] ];
  }

  return true;
}

function constructYamlPairs(data) {
  if (data === null) return [];

  var index, length, pair, keys, result,
      object = data;

  result = new Array(object.length);

  for (index = 0, length = object.length; index < length; index += 1) {
    pair = object[index];

    keys = Object.keys(pair);

    result[index] = [ keys[0], pair[keys[0]] ];
  }

  return result;
}

var pairs = new type('tag:yaml.org,2002:pairs', {
  kind: 'sequence',
  resolve: resolveYamlPairs,
  construct: constructYamlPairs
});

var _hasOwnProperty$2 = Object.prototype.hasOwnProperty;

function resolveYamlSet(data) {
  if (data === null) return true;

  var key, object = data;

  for (key in object) {
    if (_hasOwnProperty$2.call(object, key)) {
      if (object[key] !== null) return false;
    }
  }

  return true;
}

function constructYamlSet(data) {
  return data !== null ? data : {};
}

var set = new type('tag:yaml.org,2002:set', {
  kind: 'mapping',
  resolve: resolveYamlSet,
  construct: constructYamlSet
});

var _default = core.extend({
  implicit: [
    timestamp,
    merge
  ],
  explicit: [
    binary,
    omap,
    pairs,
    set
  ]
});

/*eslint-disable max-len,no-use-before-define*/







var _hasOwnProperty$1 = Object.prototype.hasOwnProperty;


var CONTEXT_FLOW_IN   = 1;
var CONTEXT_FLOW_OUT  = 2;
var CONTEXT_BLOCK_IN  = 3;
var CONTEXT_BLOCK_OUT = 4;


var CHOMPING_CLIP  = 1;
var CHOMPING_STRIP = 2;
var CHOMPING_KEEP  = 3;


var PATTERN_NON_PRINTABLE         = /[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x84\x86-\x9F\uFFFE\uFFFF]|[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?:[^\uD800-\uDBFF]|^)[\uDC00-\uDFFF]/;
var PATTERN_NON_ASCII_LINE_BREAKS = /[\x85\u2028\u2029]/;
var PATTERN_FLOW_INDICATORS       = /[,\[\]\{\}]/;
var PATTERN_TAG_HANDLE            = /^(?:!|!!|![a-z\-]+!)$/i;
var PATTERN_TAG_URI               = /^(?:!|[^,\[\]\{\}])(?:%[0-9a-f]{2}|[0-9a-z\-#;\/\?:@&=\+\$,_\.!~\*'\(\)\[\]])*$/i;


function _class(obj) { return Object.prototype.toString.call(obj); }

function is_EOL(c) {
  return (c === 0x0A/* LF */) || (c === 0x0D/* CR */);
}

function is_WHITE_SPACE(c) {
  return (c === 0x09/* Tab */) || (c === 0x20/* Space */);
}

function is_WS_OR_EOL(c) {
  return (c === 0x09/* Tab */) ||
         (c === 0x20/* Space */) ||
         (c === 0x0A/* LF */) ||
         (c === 0x0D/* CR */);
}

function is_FLOW_INDICATOR(c) {
  return c === 0x2C/* , */ ||
         c === 0x5B/* [ */ ||
         c === 0x5D/* ] */ ||
         c === 0x7B/* { */ ||
         c === 0x7D/* } */;
}

function fromHexCode(c) {
  var lc;

  if ((0x30/* 0 */ <= c) && (c <= 0x39/* 9 */)) {
    return c - 0x30;
  }

  /*eslint-disable no-bitwise*/
  lc = c | 0x20;

  if ((0x61/* a */ <= lc) && (lc <= 0x66/* f */)) {
    return lc - 0x61 + 10;
  }

  return -1;
}

function escapedHexLen(c) {
  if (c === 0x78/* x */) { return 2; }
  if (c === 0x75/* u */) { return 4; }
  if (c === 0x55/* U */) { return 8; }
  return 0;
}

function fromDecimalCode(c) {
  if ((0x30/* 0 */ <= c) && (c <= 0x39/* 9 */)) {
    return c - 0x30;
  }

  return -1;
}

function simpleEscapeSequence(c) {
  /* eslint-disable indent */
  return (c === 0x30/* 0 */) ? '\x00' :
        (c === 0x61/* a */) ? '\x07' :
        (c === 0x62/* b */) ? '\x08' :
        (c === 0x74/* t */) ? '\x09' :
        (c === 0x09/* Tab */) ? '\x09' :
        (c === 0x6E/* n */) ? '\x0A' :
        (c === 0x76/* v */) ? '\x0B' :
        (c === 0x66/* f */) ? '\x0C' :
        (c === 0x72/* r */) ? '\x0D' :
        (c === 0x65/* e */) ? '\x1B' :
        (c === 0x20/* Space */) ? ' ' :
        (c === 0x22/* " */) ? '\x22' :
        (c === 0x2F/* / */) ? '/' :
        (c === 0x5C/* \ */) ? '\x5C' :
        (c === 0x4E/* N */) ? '\x85' :
        (c === 0x5F/* _ */) ? '\xA0' :
        (c === 0x4C/* L */) ? '\u2028' :
        (c === 0x50/* P */) ? '\u2029' : '';
}

function charFromCodepoint(c) {
  if (c <= 0xFFFF) {
    return String.fromCharCode(c);
  }
  // Encode UTF-16 surrogate pair
  // https://en.wikipedia.org/wiki/UTF-16#Code_points_U.2B010000_to_U.2B10FFFF
  return String.fromCharCode(
    ((c - 0x010000) >> 10) + 0xD800,
    ((c - 0x010000) & 0x03FF) + 0xDC00
  );
}

// set a property of a literal object, while protecting against prototype pollution,
// see https://github.com/nodeca/js-yaml/issues/164 for more details
function setProperty(object, key, value) {
  // used for this specific key only because Object.defineProperty is slow
  if (key === '__proto__') {
    Object.defineProperty(object, key, {
      configurable: true,
      enumerable: true,
      writable: true,
      value: value
    });
  } else {
    object[key] = value;
  }
}

var simpleEscapeCheck = new Array(256); // integer, for fast access
var simpleEscapeMap = new Array(256);
for (var i = 0; i < 256; i++) {
  simpleEscapeCheck[i] = simpleEscapeSequence(i) ? 1 : 0;
  simpleEscapeMap[i] = simpleEscapeSequence(i);
}


function State$1(input, options) {
  this.input = input;

  this.filename  = options['filename']  || null;
  this.schema    = options['schema']    || _default;
  this.onWarning = options['onWarning'] || null;
  // (Hidden) Remove? makes the loader to expect YAML 1.1 documents
  // if such documents have no explicit %YAML directive
  this.legacy    = options['legacy']    || false;

  this.json      = options['json']      || false;
  this.listener  = options['listener']  || null;

  this.implicitTypes = this.schema.compiledImplicit;
  this.typeMap       = this.schema.compiledTypeMap;

  this.length     = input.length;
  this.position   = 0;
  this.line       = 0;
  this.lineStart  = 0;
  this.lineIndent = 0;

  // position of first leading tab in the current line,
  // used to make sure there are no tabs in the indentation
  this.firstTabInLine = -1;

  this.documents = [];

  /*
  this.version;
  this.checkLineBreaks;
  this.tagMap;
  this.anchorMap;
  this.tag;
  this.anchor;
  this.kind;
  this.result;*/

}


function generateError(state, message) {
  var mark = {
    name:     state.filename,
    buffer:   state.input.slice(0, -1), // omit trailing \0
    position: state.position,
    line:     state.line,
    column:   state.position - state.lineStart
  };

  mark.snippet = snippet(mark);

  return new exception(message, mark);
}

function throwError(state, message) {
  throw generateError(state, message);
}

function throwWarning(state, message) {
  if (state.onWarning) {
    state.onWarning.call(null, generateError(state, message));
  }
}


var directiveHandlers = {

  YAML: function handleYamlDirective(state, name, args) {

    var match, major, minor;

    if (state.version !== null) {
      throwError(state, 'duplication of %YAML directive');
    }

    if (args.length !== 1) {
      throwError(state, 'YAML directive accepts exactly one argument');
    }

    match = /^([0-9]+)\.([0-9]+)$/.exec(args[0]);

    if (match === null) {
      throwError(state, 'ill-formed argument of the YAML directive');
    }

    major = parseInt(match[1], 10);
    minor = parseInt(match[2], 10);

    if (major !== 1) {
      throwError(state, 'unacceptable YAML version of the document');
    }

    state.version = args[0];
    state.checkLineBreaks = (minor < 2);

    if (minor !== 1 && minor !== 2) {
      throwWarning(state, 'unsupported YAML version of the document');
    }
  },

  TAG: function handleTagDirective(state, name, args) {

    var handle, prefix;

    if (args.length !== 2) {
      throwError(state, 'TAG directive accepts exactly two arguments');
    }

    handle = args[0];
    prefix = args[1];

    if (!PATTERN_TAG_HANDLE.test(handle)) {
      throwError(state, 'ill-formed tag handle (first argument) of the TAG directive');
    }

    if (_hasOwnProperty$1.call(state.tagMap, handle)) {
      throwError(state, 'there is a previously declared suffix for "' + handle + '" tag handle');
    }

    if (!PATTERN_TAG_URI.test(prefix)) {
      throwError(state, 'ill-formed tag prefix (second argument) of the TAG directive');
    }

    try {
      prefix = decodeURIComponent(prefix);
    } catch (err) {
      throwError(state, 'tag prefix is malformed: ' + prefix);
    }

    state.tagMap[handle] = prefix;
  }
};


function captureSegment(state, start, end, checkJson) {
  var _position, _length, _character, _result;

  if (start < end) {
    _result = state.input.slice(start, end);

    if (checkJson) {
      for (_position = 0, _length = _result.length; _position < _length; _position += 1) {
        _character = _result.charCodeAt(_position);
        if (!(_character === 0x09 ||
              (0x20 <= _character && _character <= 0x10FFFF))) {
          throwError(state, 'expected valid JSON character');
        }
      }
    } else if (PATTERN_NON_PRINTABLE.test(_result)) {
      throwError(state, 'the stream contains non-printable characters');
    }

    state.result += _result;
  }
}

function mergeMappings(state, destination, source, overridableKeys) {
  var sourceKeys, key, index, quantity;

  if (!common.isObject(source)) {
    throwError(state, 'cannot merge mappings; the provided source object is unacceptable');
  }

  sourceKeys = Object.keys(source);

  for (index = 0, quantity = sourceKeys.length; index < quantity; index += 1) {
    key = sourceKeys[index];

    if (!_hasOwnProperty$1.call(destination, key)) {
      setProperty(destination, key, source[key]);
      overridableKeys[key] = true;
    }
  }
}

function storeMappingPair(state, _result, overridableKeys, keyTag, keyNode, valueNode,
  startLine, startLineStart, startPos) {

  var index, quantity;

  // The output is a plain object here, so keys can only be strings.
  // We need to convert keyNode to a string, but doing so can hang the process
  // (deeply nested arrays that explode exponentially using aliases).
  if (Array.isArray(keyNode)) {
    keyNode = Array.prototype.slice.call(keyNode);

    for (index = 0, quantity = keyNode.length; index < quantity; index += 1) {
      if (Array.isArray(keyNode[index])) {
        throwError(state, 'nested arrays are not supported inside keys');
      }

      if (typeof keyNode === 'object' && _class(keyNode[index]) === '[object Object]') {
        keyNode[index] = '[object Object]';
      }
    }
  }

  // Avoid code execution in load() via toString property
  // (still use its own toString for arrays, timestamps,
  // and whatever user schema extensions happen to have @@toStringTag)
  if (typeof keyNode === 'object' && _class(keyNode) === '[object Object]') {
    keyNode = '[object Object]';
  }


  keyNode = String(keyNode);

  if (_result === null) {
    _result = {};
  }

  if (keyTag === 'tag:yaml.org,2002:merge') {
    if (Array.isArray(valueNode)) {
      for (index = 0, quantity = valueNode.length; index < quantity; index += 1) {
        mergeMappings(state, _result, valueNode[index], overridableKeys);
      }
    } else {
      mergeMappings(state, _result, valueNode, overridableKeys);
    }
  } else {
    if (!state.json &&
        !_hasOwnProperty$1.call(overridableKeys, keyNode) &&
        _hasOwnProperty$1.call(_result, keyNode)) {
      state.line = startLine || state.line;
      state.lineStart = startLineStart || state.lineStart;
      state.position = startPos || state.position;
      throwError(state, 'duplicated mapping key');
    }

    setProperty(_result, keyNode, valueNode);
    delete overridableKeys[keyNode];
  }

  return _result;
}

function readLineBreak(state) {
  var ch;

  ch = state.input.charCodeAt(state.position);

  if (ch === 0x0A/* LF */) {
    state.position++;
  } else if (ch === 0x0D/* CR */) {
    state.position++;
    if (state.input.charCodeAt(state.position) === 0x0A/* LF */) {
      state.position++;
    }
  } else {
    throwError(state, 'a line break is expected');
  }

  state.line += 1;
  state.lineStart = state.position;
  state.firstTabInLine = -1;
}

function skipSeparationSpace(state, allowComments, checkIndent) {
  var lineBreaks = 0,
      ch = state.input.charCodeAt(state.position);

  while (ch !== 0) {
    while (is_WHITE_SPACE(ch)) {
      if (ch === 0x09/* Tab */ && state.firstTabInLine === -1) {
        state.firstTabInLine = state.position;
      }
      ch = state.input.charCodeAt(++state.position);
    }

    if (allowComments && ch === 0x23/* # */) {
      do {
        ch = state.input.charCodeAt(++state.position);
      } while (ch !== 0x0A/* LF */ && ch !== 0x0D/* CR */ && ch !== 0);
    }

    if (is_EOL(ch)) {
      readLineBreak(state);

      ch = state.input.charCodeAt(state.position);
      lineBreaks++;
      state.lineIndent = 0;

      while (ch === 0x20/* Space */) {
        state.lineIndent++;
        ch = state.input.charCodeAt(++state.position);
      }
    } else {
      break;
    }
  }

  if (checkIndent !== -1 && lineBreaks !== 0 && state.lineIndent < checkIndent) {
    throwWarning(state, 'deficient indentation');
  }

  return lineBreaks;
}

function testDocumentSeparator(state) {
  var _position = state.position,
      ch;

  ch = state.input.charCodeAt(_position);

  // Condition state.position === state.lineStart is tested
  // in parent on each call, for efficiency. No needs to test here again.
  if ((ch === 0x2D/* - */ || ch === 0x2E/* . */) &&
      ch === state.input.charCodeAt(_position + 1) &&
      ch === state.input.charCodeAt(_position + 2)) {

    _position += 3;

    ch = state.input.charCodeAt(_position);

    if (ch === 0 || is_WS_OR_EOL(ch)) {
      return true;
    }
  }

  return false;
}

function writeFoldedLines(state, count) {
  if (count === 1) {
    state.result += ' ';
  } else if (count > 1) {
    state.result += common.repeat('\n', count - 1);
  }
}


function readPlainScalar(state, nodeIndent, withinFlowCollection) {
  var preceding,
      following,
      captureStart,
      captureEnd,
      hasPendingContent,
      _line,
      _lineStart,
      _lineIndent,
      _kind = state.kind,
      _result = state.result,
      ch;

  ch = state.input.charCodeAt(state.position);

  if (is_WS_OR_EOL(ch)      ||
      is_FLOW_INDICATOR(ch) ||
      ch === 0x23/* # */    ||
      ch === 0x26/* & */    ||
      ch === 0x2A/* * */    ||
      ch === 0x21/* ! */    ||
      ch === 0x7C/* | */    ||
      ch === 0x3E/* > */    ||
      ch === 0x27/* ' */    ||
      ch === 0x22/* " */    ||
      ch === 0x25/* % */    ||
      ch === 0x40/* @ */    ||
      ch === 0x60/* ` */) {
    return false;
  }

  if (ch === 0x3F/* ? */ || ch === 0x2D/* - */) {
    following = state.input.charCodeAt(state.position + 1);

    if (is_WS_OR_EOL(following) ||
        withinFlowCollection && is_FLOW_INDICATOR(following)) {
      return false;
    }
  }

  state.kind = 'scalar';
  state.result = '';
  captureStart = captureEnd = state.position;
  hasPendingContent = false;

  while (ch !== 0) {
    if (ch === 0x3A/* : */) {
      following = state.input.charCodeAt(state.position + 1);

      if (is_WS_OR_EOL(following) ||
          withinFlowCollection && is_FLOW_INDICATOR(following)) {
        break;
      }

    } else if (ch === 0x23/* # */) {
      preceding = state.input.charCodeAt(state.position - 1);

      if (is_WS_OR_EOL(preceding)) {
        break;
      }

    } else if ((state.position === state.lineStart && testDocumentSeparator(state)) ||
               withinFlowCollection && is_FLOW_INDICATOR(ch)) {
      break;

    } else if (is_EOL(ch)) {
      _line = state.line;
      _lineStart = state.lineStart;
      _lineIndent = state.lineIndent;
      skipSeparationSpace(state, false, -1);

      if (state.lineIndent >= nodeIndent) {
        hasPendingContent = true;
        ch = state.input.charCodeAt(state.position);
        continue;
      } else {
        state.position = captureEnd;
        state.line = _line;
        state.lineStart = _lineStart;
        state.lineIndent = _lineIndent;
        break;
      }
    }

    if (hasPendingContent) {
      captureSegment(state, captureStart, captureEnd, false);
      writeFoldedLines(state, state.line - _line);
      captureStart = captureEnd = state.position;
      hasPendingContent = false;
    }

    if (!is_WHITE_SPACE(ch)) {
      captureEnd = state.position + 1;
    }

    ch = state.input.charCodeAt(++state.position);
  }

  captureSegment(state, captureStart, captureEnd, false);

  if (state.result) {
    return true;
  }

  state.kind = _kind;
  state.result = _result;
  return false;
}

function readSingleQuotedScalar(state, nodeIndent) {
  var ch,
      captureStart, captureEnd;

  ch = state.input.charCodeAt(state.position);

  if (ch !== 0x27/* ' */) {
    return false;
  }

  state.kind = 'scalar';
  state.result = '';
  state.position++;
  captureStart = captureEnd = state.position;

  while ((ch = state.input.charCodeAt(state.position)) !== 0) {
    if (ch === 0x27/* ' */) {
      captureSegment(state, captureStart, state.position, true);
      ch = state.input.charCodeAt(++state.position);

      if (ch === 0x27/* ' */) {
        captureStart = state.position;
        state.position++;
        captureEnd = state.position;
      } else {
        return true;
      }

    } else if (is_EOL(ch)) {
      captureSegment(state, captureStart, captureEnd, true);
      writeFoldedLines(state, skipSeparationSpace(state, false, nodeIndent));
      captureStart = captureEnd = state.position;

    } else if (state.position === state.lineStart && testDocumentSeparator(state)) {
      throwError(state, 'unexpected end of the document within a single quoted scalar');

    } else {
      state.position++;
      captureEnd = state.position;
    }
  }

  throwError(state, 'unexpected end of the stream within a single quoted scalar');
}

function readDoubleQuotedScalar(state, nodeIndent) {
  var captureStart,
      captureEnd,
      hexLength,
      hexResult,
      tmp,
      ch;

  ch = state.input.charCodeAt(state.position);

  if (ch !== 0x22/* " */) {
    return false;
  }

  state.kind = 'scalar';
  state.result = '';
  state.position++;
  captureStart = captureEnd = state.position;

  while ((ch = state.input.charCodeAt(state.position)) !== 0) {
    if (ch === 0x22/* " */) {
      captureSegment(state, captureStart, state.position, true);
      state.position++;
      return true;

    } else if (ch === 0x5C/* \ */) {
      captureSegment(state, captureStart, state.position, true);
      ch = state.input.charCodeAt(++state.position);

      if (is_EOL(ch)) {
        skipSeparationSpace(state, false, nodeIndent);

        // TODO: rework to inline fn with no type cast?
      } else if (ch < 256 && simpleEscapeCheck[ch]) {
        state.result += simpleEscapeMap[ch];
        state.position++;

      } else if ((tmp = escapedHexLen(ch)) > 0) {
        hexLength = tmp;
        hexResult = 0;

        for (; hexLength > 0; hexLength--) {
          ch = state.input.charCodeAt(++state.position);

          if ((tmp = fromHexCode(ch)) >= 0) {
            hexResult = (hexResult << 4) + tmp;

          } else {
            throwError(state, 'expected hexadecimal character');
          }
        }

        state.result += charFromCodepoint(hexResult);

        state.position++;

      } else {
        throwError(state, 'unknown escape sequence');
      }

      captureStart = captureEnd = state.position;

    } else if (is_EOL(ch)) {
      captureSegment(state, captureStart, captureEnd, true);
      writeFoldedLines(state, skipSeparationSpace(state, false, nodeIndent));
      captureStart = captureEnd = state.position;

    } else if (state.position === state.lineStart && testDocumentSeparator(state)) {
      throwError(state, 'unexpected end of the document within a double quoted scalar');

    } else {
      state.position++;
      captureEnd = state.position;
    }
  }

  throwError(state, 'unexpected end of the stream within a double quoted scalar');
}

function readFlowCollection(state, nodeIndent) {
  var readNext = true,
      _line,
      _lineStart,
      _pos,
      _tag     = state.tag,
      _result,
      _anchor  = state.anchor,
      following,
      terminator,
      isPair,
      isExplicitPair,
      isMapping,
      overridableKeys = Object.create(null),
      keyNode,
      keyTag,
      valueNode,
      ch;

  ch = state.input.charCodeAt(state.position);

  if (ch === 0x5B/* [ */) {
    terminator = 0x5D;/* ] */
    isMapping = false;
    _result = [];
  } else if (ch === 0x7B/* { */) {
    terminator = 0x7D;/* } */
    isMapping = true;
    _result = {};
  } else {
    return false;
  }

  if (state.anchor !== null) {
    state.anchorMap[state.anchor] = _result;
  }

  ch = state.input.charCodeAt(++state.position);

  while (ch !== 0) {
    skipSeparationSpace(state, true, nodeIndent);

    ch = state.input.charCodeAt(state.position);

    if (ch === terminator) {
      state.position++;
      state.tag = _tag;
      state.anchor = _anchor;
      state.kind = isMapping ? 'mapping' : 'sequence';
      state.result = _result;
      return true;
    } else if (!readNext) {
      throwError(state, 'missed comma between flow collection entries');
    } else if (ch === 0x2C/* , */) {
      // "flow collection entries can never be completely empty", as per YAML 1.2, section 7.4
      throwError(state, "expected the node content, but found ','");
    }

    keyTag = keyNode = valueNode = null;
    isPair = isExplicitPair = false;

    if (ch === 0x3F/* ? */) {
      following = state.input.charCodeAt(state.position + 1);

      if (is_WS_OR_EOL(following)) {
        isPair = isExplicitPair = true;
        state.position++;
        skipSeparationSpace(state, true, nodeIndent);
      }
    }

    _line = state.line; // Save the current line.
    _lineStart = state.lineStart;
    _pos = state.position;
    composeNode(state, nodeIndent, CONTEXT_FLOW_IN, false, true);
    keyTag = state.tag;
    keyNode = state.result;
    skipSeparationSpace(state, true, nodeIndent);

    ch = state.input.charCodeAt(state.position);

    if ((isExplicitPair || state.line === _line) && ch === 0x3A/* : */) {
      isPair = true;
      ch = state.input.charCodeAt(++state.position);
      skipSeparationSpace(state, true, nodeIndent);
      composeNode(state, nodeIndent, CONTEXT_FLOW_IN, false, true);
      valueNode = state.result;
    }

    if (isMapping) {
      storeMappingPair(state, _result, overridableKeys, keyTag, keyNode, valueNode, _line, _lineStart, _pos);
    } else if (isPair) {
      _result.push(storeMappingPair(state, null, overridableKeys, keyTag, keyNode, valueNode, _line, _lineStart, _pos));
    } else {
      _result.push(keyNode);
    }

    skipSeparationSpace(state, true, nodeIndent);

    ch = state.input.charCodeAt(state.position);

    if (ch === 0x2C/* , */) {
      readNext = true;
      ch = state.input.charCodeAt(++state.position);
    } else {
      readNext = false;
    }
  }

  throwError(state, 'unexpected end of the stream within a flow collection');
}

function readBlockScalar(state, nodeIndent) {
  var captureStart,
      folding,
      chomping       = CHOMPING_CLIP,
      didReadContent = false,
      detectedIndent = false,
      textIndent     = nodeIndent,
      emptyLines     = 0,
      atMoreIndented = false,
      tmp,
      ch;

  ch = state.input.charCodeAt(state.position);

  if (ch === 0x7C/* | */) {
    folding = false;
  } else if (ch === 0x3E/* > */) {
    folding = true;
  } else {
    return false;
  }

  state.kind = 'scalar';
  state.result = '';

  while (ch !== 0) {
    ch = state.input.charCodeAt(++state.position);

    if (ch === 0x2B/* + */ || ch === 0x2D/* - */) {
      if (CHOMPING_CLIP === chomping) {
        chomping = (ch === 0x2B/* + */) ? CHOMPING_KEEP : CHOMPING_STRIP;
      } else {
        throwError(state, 'repeat of a chomping mode identifier');
      }

    } else if ((tmp = fromDecimalCode(ch)) >= 0) {
      if (tmp === 0) {
        throwError(state, 'bad explicit indentation width of a block scalar; it cannot be less than one');
      } else if (!detectedIndent) {
        textIndent = nodeIndent + tmp - 1;
        detectedIndent = true;
      } else {
        throwError(state, 'repeat of an indentation width identifier');
      }

    } else {
      break;
    }
  }

  if (is_WHITE_SPACE(ch)) {
    do { ch = state.input.charCodeAt(++state.position); }
    while (is_WHITE_SPACE(ch));

    if (ch === 0x23/* # */) {
      do { ch = state.input.charCodeAt(++state.position); }
      while (!is_EOL(ch) && (ch !== 0));
    }
  }

  while (ch !== 0) {
    readLineBreak(state);
    state.lineIndent = 0;

    ch = state.input.charCodeAt(state.position);

    while ((!detectedIndent || state.lineIndent < textIndent) &&
           (ch === 0x20/* Space */)) {
      state.lineIndent++;
      ch = state.input.charCodeAt(++state.position);
    }

    if (!detectedIndent && state.lineIndent > textIndent) {
      textIndent = state.lineIndent;
    }

    if (is_EOL(ch)) {
      emptyLines++;
      continue;
    }

    // End of the scalar.
    if (state.lineIndent < textIndent) {

      // Perform the chomping.
      if (chomping === CHOMPING_KEEP) {
        state.result += common.repeat('\n', didReadContent ? 1 + emptyLines : emptyLines);
      } else if (chomping === CHOMPING_CLIP) {
        if (didReadContent) { // i.e. only if the scalar is not empty.
          state.result += '\n';
        }
      }

      // Break this `while` cycle and go to the funciton's epilogue.
      break;
    }

    // Folded style: use fancy rules to handle line breaks.
    if (folding) {

      // Lines starting with white space characters (more-indented lines) are not folded.
      if (is_WHITE_SPACE(ch)) {
        atMoreIndented = true;
        // except for the first content line (cf. Example 8.1)
        state.result += common.repeat('\n', didReadContent ? 1 + emptyLines : emptyLines);

      // End of more-indented block.
      } else if (atMoreIndented) {
        atMoreIndented = false;
        state.result += common.repeat('\n', emptyLines + 1);

      // Just one line break - perceive as the same line.
      } else if (emptyLines === 0) {
        if (didReadContent) { // i.e. only if we have already read some scalar content.
          state.result += ' ';
        }

      // Several line breaks - perceive as different lines.
      } else {
        state.result += common.repeat('\n', emptyLines);
      }

    // Literal style: just add exact number of line breaks between content lines.
    } else {
      // Keep all line breaks except the header line break.
      state.result += common.repeat('\n', didReadContent ? 1 + emptyLines : emptyLines);
    }

    didReadContent = true;
    detectedIndent = true;
    emptyLines = 0;
    captureStart = state.position;

    while (!is_EOL(ch) && (ch !== 0)) {
      ch = state.input.charCodeAt(++state.position);
    }

    captureSegment(state, captureStart, state.position, false);
  }

  return true;
}

function readBlockSequence(state, nodeIndent) {
  var _line,
      _tag      = state.tag,
      _anchor   = state.anchor,
      _result   = [],
      following,
      detected  = false,
      ch;

  // there is a leading tab before this token, so it can't be a block sequence/mapping;
  // it can still be flow sequence/mapping or a scalar
  if (state.firstTabInLine !== -1) return false;

  if (state.anchor !== null) {
    state.anchorMap[state.anchor] = _result;
  }

  ch = state.input.charCodeAt(state.position);

  while (ch !== 0) {
    if (state.firstTabInLine !== -1) {
      state.position = state.firstTabInLine;
      throwError(state, 'tab characters must not be used in indentation');
    }

    if (ch !== 0x2D/* - */) {
      break;
    }

    following = state.input.charCodeAt(state.position + 1);

    if (!is_WS_OR_EOL(following)) {
      break;
    }

    detected = true;
    state.position++;

    if (skipSeparationSpace(state, true, -1)) {
      if (state.lineIndent <= nodeIndent) {
        _result.push(null);
        ch = state.input.charCodeAt(state.position);
        continue;
      }
    }

    _line = state.line;
    composeNode(state, nodeIndent, CONTEXT_BLOCK_IN, false, true);
    _result.push(state.result);
    skipSeparationSpace(state, true, -1);

    ch = state.input.charCodeAt(state.position);

    if ((state.line === _line || state.lineIndent > nodeIndent) && (ch !== 0)) {
      throwError(state, 'bad indentation of a sequence entry');
    } else if (state.lineIndent < nodeIndent) {
      break;
    }
  }

  if (detected) {
    state.tag = _tag;
    state.anchor = _anchor;
    state.kind = 'sequence';
    state.result = _result;
    return true;
  }
  return false;
}

function readBlockMapping(state, nodeIndent, flowIndent) {
  var following,
      allowCompact,
      _line,
      _keyLine,
      _keyLineStart,
      _keyPos,
      _tag          = state.tag,
      _anchor       = state.anchor,
      _result       = {},
      overridableKeys = Object.create(null),
      keyTag        = null,
      keyNode       = null,
      valueNode     = null,
      atExplicitKey = false,
      detected      = false,
      ch;

  // there is a leading tab before this token, so it can't be a block sequence/mapping;
  // it can still be flow sequence/mapping or a scalar
  if (state.firstTabInLine !== -1) return false;

  if (state.anchor !== null) {
    state.anchorMap[state.anchor] = _result;
  }

  ch = state.input.charCodeAt(state.position);

  while (ch !== 0) {
    if (!atExplicitKey && state.firstTabInLine !== -1) {
      state.position = state.firstTabInLine;
      throwError(state, 'tab characters must not be used in indentation');
    }

    following = state.input.charCodeAt(state.position + 1);
    _line = state.line; // Save the current line.

    //
    // Explicit notation case. There are two separate blocks:
    // first for the key (denoted by "?") and second for the value (denoted by ":")
    //
    if ((ch === 0x3F/* ? */ || ch === 0x3A/* : */) && is_WS_OR_EOL(following)) {

      if (ch === 0x3F/* ? */) {
        if (atExplicitKey) {
          storeMappingPair(state, _result, overridableKeys, keyTag, keyNode, null, _keyLine, _keyLineStart, _keyPos);
          keyTag = keyNode = valueNode = null;
        }

        detected = true;
        atExplicitKey = true;
        allowCompact = true;

      } else if (atExplicitKey) {
        // i.e. 0x3A/* : */ === character after the explicit key.
        atExplicitKey = false;
        allowCompact = true;

      } else {
        throwError(state, 'incomplete explicit mapping pair; a key node is missed; or followed by a non-tabulated empty line');
      }

      state.position += 1;
      ch = following;

    //
    // Implicit notation case. Flow-style node as the key first, then ":", and the value.
    //
    } else {
      _keyLine = state.line;
      _keyLineStart = state.lineStart;
      _keyPos = state.position;

      if (!composeNode(state, flowIndent, CONTEXT_FLOW_OUT, false, true)) {
        // Neither implicit nor explicit notation.
        // Reading is done. Go to the epilogue.
        break;
      }

      if (state.line === _line) {
        ch = state.input.charCodeAt(state.position);

        while (is_WHITE_SPACE(ch)) {
          ch = state.input.charCodeAt(++state.position);
        }

        if (ch === 0x3A/* : */) {
          ch = state.input.charCodeAt(++state.position);

          if (!is_WS_OR_EOL(ch)) {
            throwError(state, 'a whitespace character is expected after the key-value separator within a block mapping');
          }

          if (atExplicitKey) {
            storeMappingPair(state, _result, overridableKeys, keyTag, keyNode, null, _keyLine, _keyLineStart, _keyPos);
            keyTag = keyNode = valueNode = null;
          }

          detected = true;
          atExplicitKey = false;
          allowCompact = false;
          keyTag = state.tag;
          keyNode = state.result;

        } else if (detected) {
          throwError(state, 'can not read an implicit mapping pair; a colon is missed');

        } else {
          state.tag = _tag;
          state.anchor = _anchor;
          return true; // Keep the result of `composeNode`.
        }

      } else if (detected) {
        throwError(state, 'can not read a block mapping entry; a multiline key may not be an implicit key');

      } else {
        state.tag = _tag;
        state.anchor = _anchor;
        return true; // Keep the result of `composeNode`.
      }
    }

    //
    // Common reading code for both explicit and implicit notations.
    //
    if (state.line === _line || state.lineIndent > nodeIndent) {
      if (atExplicitKey) {
        _keyLine = state.line;
        _keyLineStart = state.lineStart;
        _keyPos = state.position;
      }

      if (composeNode(state, nodeIndent, CONTEXT_BLOCK_OUT, true, allowCompact)) {
        if (atExplicitKey) {
          keyNode = state.result;
        } else {
          valueNode = state.result;
        }
      }

      if (!atExplicitKey) {
        storeMappingPair(state, _result, overridableKeys, keyTag, keyNode, valueNode, _keyLine, _keyLineStart, _keyPos);
        keyTag = keyNode = valueNode = null;
      }

      skipSeparationSpace(state, true, -1);
      ch = state.input.charCodeAt(state.position);
    }

    if ((state.line === _line || state.lineIndent > nodeIndent) && (ch !== 0)) {
      throwError(state, 'bad indentation of a mapping entry');
    } else if (state.lineIndent < nodeIndent) {
      break;
    }
  }

  //
  // Epilogue.
  //

  // Special case: last mapping's node contains only the key in explicit notation.
  if (atExplicitKey) {
    storeMappingPair(state, _result, overridableKeys, keyTag, keyNode, null, _keyLine, _keyLineStart, _keyPos);
  }

  // Expose the resulting mapping.
  if (detected) {
    state.tag = _tag;
    state.anchor = _anchor;
    state.kind = 'mapping';
    state.result = _result;
  }

  return detected;
}

function readTagProperty(state) {
  var _position,
      isVerbatim = false,
      isNamed    = false,
      tagHandle,
      tagName,
      ch;

  ch = state.input.charCodeAt(state.position);

  if (ch !== 0x21/* ! */) return false;

  if (state.tag !== null) {
    throwError(state, 'duplication of a tag property');
  }

  ch = state.input.charCodeAt(++state.position);

  if (ch === 0x3C/* < */) {
    isVerbatim = true;
    ch = state.input.charCodeAt(++state.position);

  } else if (ch === 0x21/* ! */) {
    isNamed = true;
    tagHandle = '!!';
    ch = state.input.charCodeAt(++state.position);

  } else {
    tagHandle = '!';
  }

  _position = state.position;

  if (isVerbatim) {
    do { ch = state.input.charCodeAt(++state.position); }
    while (ch !== 0 && ch !== 0x3E/* > */);

    if (state.position < state.length) {
      tagName = state.input.slice(_position, state.position);
      ch = state.input.charCodeAt(++state.position);
    } else {
      throwError(state, 'unexpected end of the stream within a verbatim tag');
    }
  } else {
    while (ch !== 0 && !is_WS_OR_EOL(ch)) {

      if (ch === 0x21/* ! */) {
        if (!isNamed) {
          tagHandle = state.input.slice(_position - 1, state.position + 1);

          if (!PATTERN_TAG_HANDLE.test(tagHandle)) {
            throwError(state, 'named tag handle cannot contain such characters');
          }

          isNamed = true;
          _position = state.position + 1;
        } else {
          throwError(state, 'tag suffix cannot contain exclamation marks');
        }
      }

      ch = state.input.charCodeAt(++state.position);
    }

    tagName = state.input.slice(_position, state.position);

    if (PATTERN_FLOW_INDICATORS.test(tagName)) {
      throwError(state, 'tag suffix cannot contain flow indicator characters');
    }
  }

  if (tagName && !PATTERN_TAG_URI.test(tagName)) {
    throwError(state, 'tag name cannot contain such characters: ' + tagName);
  }

  try {
    tagName = decodeURIComponent(tagName);
  } catch (err) {
    throwError(state, 'tag name is malformed: ' + tagName);
  }

  if (isVerbatim) {
    state.tag = tagName;

  } else if (_hasOwnProperty$1.call(state.tagMap, tagHandle)) {
    state.tag = state.tagMap[tagHandle] + tagName;

  } else if (tagHandle === '!') {
    state.tag = '!' + tagName;

  } else if (tagHandle === '!!') {
    state.tag = 'tag:yaml.org,2002:' + tagName;

  } else {
    throwError(state, 'undeclared tag handle "' + tagHandle + '"');
  }

  return true;
}

function readAnchorProperty(state) {
  var _position,
      ch;

  ch = state.input.charCodeAt(state.position);

  if (ch !== 0x26/* & */) return false;

  if (state.anchor !== null) {
    throwError(state, 'duplication of an anchor property');
  }

  ch = state.input.charCodeAt(++state.position);
  _position = state.position;

  while (ch !== 0 && !is_WS_OR_EOL(ch) && !is_FLOW_INDICATOR(ch)) {
    ch = state.input.charCodeAt(++state.position);
  }

  if (state.position === _position) {
    throwError(state, 'name of an anchor node must contain at least one character');
  }

  state.anchor = state.input.slice(_position, state.position);
  return true;
}

function readAlias(state) {
  var _position, alias,
      ch;

  ch = state.input.charCodeAt(state.position);

  if (ch !== 0x2A/* * */) return false;

  ch = state.input.charCodeAt(++state.position);
  _position = state.position;

  while (ch !== 0 && !is_WS_OR_EOL(ch) && !is_FLOW_INDICATOR(ch)) {
    ch = state.input.charCodeAt(++state.position);
  }

  if (state.position === _position) {
    throwError(state, 'name of an alias node must contain at least one character');
  }

  alias = state.input.slice(_position, state.position);

  if (!_hasOwnProperty$1.call(state.anchorMap, alias)) {
    throwError(state, 'unidentified alias "' + alias + '"');
  }

  state.result = state.anchorMap[alias];
  skipSeparationSpace(state, true, -1);
  return true;
}

function composeNode(state, parentIndent, nodeContext, allowToSeek, allowCompact) {
  var allowBlockStyles,
      allowBlockScalars,
      allowBlockCollections,
      indentStatus = 1, // 1: this>parent, 0: this=parent, -1: this<parent
      atNewLine  = false,
      hasContent = false,
      typeIndex,
      typeQuantity,
      typeList,
      type,
      flowIndent,
      blockIndent;

  if (state.listener !== null) {
    state.listener('open', state);
  }

  state.tag    = null;
  state.anchor = null;
  state.kind   = null;
  state.result = null;

  allowBlockStyles = allowBlockScalars = allowBlockCollections =
    CONTEXT_BLOCK_OUT === nodeContext ||
    CONTEXT_BLOCK_IN  === nodeContext;

  if (allowToSeek) {
    if (skipSeparationSpace(state, true, -1)) {
      atNewLine = true;

      if (state.lineIndent > parentIndent) {
        indentStatus = 1;
      } else if (state.lineIndent === parentIndent) {
        indentStatus = 0;
      } else if (state.lineIndent < parentIndent) {
        indentStatus = -1;
      }
    }
  }

  if (indentStatus === 1) {
    while (readTagProperty(state) || readAnchorProperty(state)) {
      if (skipSeparationSpace(state, true, -1)) {
        atNewLine = true;
        allowBlockCollections = allowBlockStyles;

        if (state.lineIndent > parentIndent) {
          indentStatus = 1;
        } else if (state.lineIndent === parentIndent) {
          indentStatus = 0;
        } else if (state.lineIndent < parentIndent) {
          indentStatus = -1;
        }
      } else {
        allowBlockCollections = false;
      }
    }
  }

  if (allowBlockCollections) {
    allowBlockCollections = atNewLine || allowCompact;
  }

  if (indentStatus === 1 || CONTEXT_BLOCK_OUT === nodeContext) {
    if (CONTEXT_FLOW_IN === nodeContext || CONTEXT_FLOW_OUT === nodeContext) {
      flowIndent = parentIndent;
    } else {
      flowIndent = parentIndent + 1;
    }

    blockIndent = state.position - state.lineStart;

    if (indentStatus === 1) {
      if (allowBlockCollections &&
          (readBlockSequence(state, blockIndent) ||
           readBlockMapping(state, blockIndent, flowIndent)) ||
          readFlowCollection(state, flowIndent)) {
        hasContent = true;
      } else {
        if ((allowBlockScalars && readBlockScalar(state, flowIndent)) ||
            readSingleQuotedScalar(state, flowIndent) ||
            readDoubleQuotedScalar(state, flowIndent)) {
          hasContent = true;

        } else if (readAlias(state)) {
          hasContent = true;

          if (state.tag !== null || state.anchor !== null) {
            throwError(state, 'alias node should not have any properties');
          }

        } else if (readPlainScalar(state, flowIndent, CONTEXT_FLOW_IN === nodeContext)) {
          hasContent = true;

          if (state.tag === null) {
            state.tag = '?';
          }
        }

        if (state.anchor !== null) {
          state.anchorMap[state.anchor] = state.result;
        }
      }
    } else if (indentStatus === 0) {
      // Special case: block sequences are allowed to have same indentation level as the parent.
      // http://www.yaml.org/spec/1.2/spec.html#id2799784
      hasContent = allowBlockCollections && readBlockSequence(state, blockIndent);
    }
  }

  if (state.tag === null) {
    if (state.anchor !== null) {
      state.anchorMap[state.anchor] = state.result;
    }

  } else if (state.tag === '?') {
    // Implicit resolving is not allowed for non-scalar types, and '?'
    // non-specific tag is only automatically assigned to plain scalars.
    //
    // We only need to check kind conformity in case user explicitly assigns '?'
    // tag, for example like this: "!<?> [0]"
    //
    if (state.result !== null && state.kind !== 'scalar') {
      throwError(state, 'unacceptable node kind for !<?> tag; it should be "scalar", not "' + state.kind + '"');
    }

    for (typeIndex = 0, typeQuantity = state.implicitTypes.length; typeIndex < typeQuantity; typeIndex += 1) {
      type = state.implicitTypes[typeIndex];

      if (type.resolve(state.result)) { // `state.result` updated in resolver if matched
        state.result = type.construct(state.result);
        state.tag = type.tag;
        if (state.anchor !== null) {
          state.anchorMap[state.anchor] = state.result;
        }
        break;
      }
    }
  } else if (state.tag !== '!') {
    if (_hasOwnProperty$1.call(state.typeMap[state.kind || 'fallback'], state.tag)) {
      type = state.typeMap[state.kind || 'fallback'][state.tag];
    } else {
      // looking for multi type
      type = null;
      typeList = state.typeMap.multi[state.kind || 'fallback'];

      for (typeIndex = 0, typeQuantity = typeList.length; typeIndex < typeQuantity; typeIndex += 1) {
        if (state.tag.slice(0, typeList[typeIndex].tag.length) === typeList[typeIndex].tag) {
          type = typeList[typeIndex];
          break;
        }
      }
    }

    if (!type) {
      throwError(state, 'unknown tag !<' + state.tag + '>');
    }

    if (state.result !== null && type.kind !== state.kind) {
      throwError(state, 'unacceptable node kind for !<' + state.tag + '> tag; it should be "' + type.kind + '", not "' + state.kind + '"');
    }

    if (!type.resolve(state.result, state.tag)) { // `state.result` updated in resolver if matched
      throwError(state, 'cannot resolve a node with !<' + state.tag + '> explicit tag');
    } else {
      state.result = type.construct(state.result, state.tag);
      if (state.anchor !== null) {
        state.anchorMap[state.anchor] = state.result;
      }
    }
  }

  if (state.listener !== null) {
    state.listener('close', state);
  }
  return state.tag !== null ||  state.anchor !== null || hasContent;
}

function readDocument(state) {
  var documentStart = state.position,
      _position,
      directiveName,
      directiveArgs,
      hasDirectives = false,
      ch;

  state.version = null;
  state.checkLineBreaks = state.legacy;
  state.tagMap = Object.create(null);
  state.anchorMap = Object.create(null);

  while ((ch = state.input.charCodeAt(state.position)) !== 0) {
    skipSeparationSpace(state, true, -1);

    ch = state.input.charCodeAt(state.position);

    if (state.lineIndent > 0 || ch !== 0x25/* % */) {
      break;
    }

    hasDirectives = true;
    ch = state.input.charCodeAt(++state.position);
    _position = state.position;

    while (ch !== 0 && !is_WS_OR_EOL(ch)) {
      ch = state.input.charCodeAt(++state.position);
    }

    directiveName = state.input.slice(_position, state.position);
    directiveArgs = [];

    if (directiveName.length < 1) {
      throwError(state, 'directive name must not be less than one character in length');
    }

    while (ch !== 0) {
      while (is_WHITE_SPACE(ch)) {
        ch = state.input.charCodeAt(++state.position);
      }

      if (ch === 0x23/* # */) {
        do { ch = state.input.charCodeAt(++state.position); }
        while (ch !== 0 && !is_EOL(ch));
        break;
      }

      if (is_EOL(ch)) break;

      _position = state.position;

      while (ch !== 0 && !is_WS_OR_EOL(ch)) {
        ch = state.input.charCodeAt(++state.position);
      }

      directiveArgs.push(state.input.slice(_position, state.position));
    }

    if (ch !== 0) readLineBreak(state);

    if (_hasOwnProperty$1.call(directiveHandlers, directiveName)) {
      directiveHandlers[directiveName](state, directiveName, directiveArgs);
    } else {
      throwWarning(state, 'unknown document directive "' + directiveName + '"');
    }
  }

  skipSeparationSpace(state, true, -1);

  if (state.lineIndent === 0 &&
      state.input.charCodeAt(state.position)     === 0x2D/* - */ &&
      state.input.charCodeAt(state.position + 1) === 0x2D/* - */ &&
      state.input.charCodeAt(state.position + 2) === 0x2D/* - */) {
    state.position += 3;
    skipSeparationSpace(state, true, -1);

  } else if (hasDirectives) {
    throwError(state, 'directives end mark is expected');
  }

  composeNode(state, state.lineIndent - 1, CONTEXT_BLOCK_OUT, false, true);
  skipSeparationSpace(state, true, -1);

  if (state.checkLineBreaks &&
      PATTERN_NON_ASCII_LINE_BREAKS.test(state.input.slice(documentStart, state.position))) {
    throwWarning(state, 'non-ASCII line breaks are interpreted as content');
  }

  state.documents.push(state.result);

  if (state.position === state.lineStart && testDocumentSeparator(state)) {

    if (state.input.charCodeAt(state.position) === 0x2E/* . */) {
      state.position += 3;
      skipSeparationSpace(state, true, -1);
    }
    return;
  }

  if (state.position < (state.length - 1)) {
    throwError(state, 'end of the stream or a document separator is expected');
  } else {
    return;
  }
}


function loadDocuments(input, options) {
  input = String(input);
  options = options || {};

  if (input.length !== 0) {

    // Add tailing `\n` if not exists
    if (input.charCodeAt(input.length - 1) !== 0x0A/* LF */ &&
        input.charCodeAt(input.length - 1) !== 0x0D/* CR */) {
      input += '\n';
    }

    // Strip BOM
    if (input.charCodeAt(0) === 0xFEFF) {
      input = input.slice(1);
    }
  }

  var state = new State$1(input, options);

  var nullpos = input.indexOf('\0');

  if (nullpos !== -1) {
    state.position = nullpos;
    throwError(state, 'null byte is not allowed in input');
  }

  // Use 0 as string terminator. That significantly simplifies bounds check.
  state.input += '\0';

  while (state.input.charCodeAt(state.position) === 0x20/* Space */) {
    state.lineIndent += 1;
    state.position += 1;
  }

  while (state.position < (state.length - 1)) {
    readDocument(state);
  }

  return state.documents;
}


function loadAll$1(input, iterator, options) {
  if (iterator !== null && typeof iterator === 'object' && typeof options === 'undefined') {
    options = iterator;
    iterator = null;
  }

  var documents = loadDocuments(input, options);

  if (typeof iterator !== 'function') {
    return documents;
  }

  for (var index = 0, length = documents.length; index < length; index += 1) {
    iterator(documents[index]);
  }
}


function load$1(input, options) {
  var documents = loadDocuments(input, options);

  if (documents.length === 0) {
    /*eslint-disable no-undefined*/
    return undefined;
  } else if (documents.length === 1) {
    return documents[0];
  }
  throw new exception('expected a single document in the stream, but found more');
}


var loadAll_1 = loadAll$1;
var load_1    = load$1;

var loader = {
	loadAll: loadAll_1,
	load: load_1
};

/*eslint-disable no-use-before-define*/





var _toString       = Object.prototype.toString;
var _hasOwnProperty = Object.prototype.hasOwnProperty;

var CHAR_BOM                  = 0xFEFF;
var CHAR_TAB                  = 0x09; /* Tab */
var CHAR_LINE_FEED            = 0x0A; /* LF */
var CHAR_CARRIAGE_RETURN      = 0x0D; /* CR */
var CHAR_SPACE                = 0x20; /* Space */
var CHAR_EXCLAMATION          = 0x21; /* ! */
var CHAR_DOUBLE_QUOTE         = 0x22; /* " */
var CHAR_SHARP                = 0x23; /* # */
var CHAR_PERCENT              = 0x25; /* % */
var CHAR_AMPERSAND            = 0x26; /* & */
var CHAR_SINGLE_QUOTE         = 0x27; /* ' */
var CHAR_ASTERISK             = 0x2A; /* * */
var CHAR_COMMA                = 0x2C; /* , */
var CHAR_MINUS                = 0x2D; /* - */
var CHAR_COLON                = 0x3A; /* : */
var CHAR_EQUALS               = 0x3D; /* = */
var CHAR_GREATER_THAN         = 0x3E; /* > */
var CHAR_QUESTION             = 0x3F; /* ? */
var CHAR_COMMERCIAL_AT        = 0x40; /* @ */
var CHAR_LEFT_SQUARE_BRACKET  = 0x5B; /* [ */
var CHAR_RIGHT_SQUARE_BRACKET = 0x5D; /* ] */
var CHAR_GRAVE_ACCENT         = 0x60; /* ` */
var CHAR_LEFT_CURLY_BRACKET   = 0x7B; /* { */
var CHAR_VERTICAL_LINE        = 0x7C; /* | */
var CHAR_RIGHT_CURLY_BRACKET  = 0x7D; /* } */

var ESCAPE_SEQUENCES = {};

ESCAPE_SEQUENCES[0x00]   = '\\0';
ESCAPE_SEQUENCES[0x07]   = '\\a';
ESCAPE_SEQUENCES[0x08]   = '\\b';
ESCAPE_SEQUENCES[0x09]   = '\\t';
ESCAPE_SEQUENCES[0x0A]   = '\\n';
ESCAPE_SEQUENCES[0x0B]   = '\\v';
ESCAPE_SEQUENCES[0x0C]   = '\\f';
ESCAPE_SEQUENCES[0x0D]   = '\\r';
ESCAPE_SEQUENCES[0x1B]   = '\\e';
ESCAPE_SEQUENCES[0x22]   = '\\"';
ESCAPE_SEQUENCES[0x5C]   = '\\\\';
ESCAPE_SEQUENCES[0x85]   = '\\N';
ESCAPE_SEQUENCES[0xA0]   = '\\_';
ESCAPE_SEQUENCES[0x2028] = '\\L';
ESCAPE_SEQUENCES[0x2029] = '\\P';

var DEPRECATED_BOOLEANS_SYNTAX = [
  'y', 'Y', 'yes', 'Yes', 'YES', 'on', 'On', 'ON',
  'n', 'N', 'no', 'No', 'NO', 'off', 'Off', 'OFF'
];

var DEPRECATED_BASE60_SYNTAX = /^[-+]?[0-9_]+(?::[0-9_]+)+(?:\.[0-9_]*)?$/;

function compileStyleMap(schema, map) {
  var result, keys, index, length, tag, style, type;

  if (map === null) return {};

  result = {};
  keys = Object.keys(map);

  for (index = 0, length = keys.length; index < length; index += 1) {
    tag = keys[index];
    style = String(map[tag]);

    if (tag.slice(0, 2) === '!!') {
      tag = 'tag:yaml.org,2002:' + tag.slice(2);
    }
    type = schema.compiledTypeMap['fallback'][tag];

    if (type && _hasOwnProperty.call(type.styleAliases, style)) {
      style = type.styleAliases[style];
    }

    result[tag] = style;
  }

  return result;
}

function encodeHex(character) {
  var string, handle, length;

  string = character.toString(16).toUpperCase();

  if (character <= 0xFF) {
    handle = 'x';
    length = 2;
  } else if (character <= 0xFFFF) {
    handle = 'u';
    length = 4;
  } else if (character <= 0xFFFFFFFF) {
    handle = 'U';
    length = 8;
  } else {
    throw new exception('code point within a string may not be greater than 0xFFFFFFFF');
  }

  return '\\' + handle + common.repeat('0', length - string.length) + string;
}


var QUOTING_TYPE_SINGLE = 1,
    QUOTING_TYPE_DOUBLE = 2;

function State(options) {
  this.schema        = options['schema'] || _default;
  this.indent        = Math.max(1, (options['indent'] || 2));
  this.noArrayIndent = options['noArrayIndent'] || false;
  this.skipInvalid   = options['skipInvalid'] || false;
  this.flowLevel     = (common.isNothing(options['flowLevel']) ? -1 : options['flowLevel']);
  this.styleMap      = compileStyleMap(this.schema, options['styles'] || null);
  this.sortKeys      = options['sortKeys'] || false;
  this.lineWidth     = options['lineWidth'] || 80;
  this.noRefs        = options['noRefs'] || false;
  this.noCompatMode  = options['noCompatMode'] || false;
  this.condenseFlow  = options['condenseFlow'] || false;
  this.quotingType   = options['quotingType'] === '"' ? QUOTING_TYPE_DOUBLE : QUOTING_TYPE_SINGLE;
  this.forceQuotes   = options['forceQuotes'] || false;
  this.replacer      = typeof options['replacer'] === 'function' ? options['replacer'] : null;

  this.implicitTypes = this.schema.compiledImplicit;
  this.explicitTypes = this.schema.compiledExplicit;

  this.tag = null;
  this.result = '';

  this.duplicates = [];
  this.usedDuplicates = null;
}

// Indents every line in a string. Empty lines (\n only) are not indented.
function indentString(string, spaces) {
  var ind = common.repeat(' ', spaces),
      position = 0,
      next = -1,
      result = '',
      line,
      length = string.length;

  while (position < length) {
    next = string.indexOf('\n', position);
    if (next === -1) {
      line = string.slice(position);
      position = length;
    } else {
      line = string.slice(position, next + 1);
      position = next + 1;
    }

    if (line.length && line !== '\n') result += ind;

    result += line;
  }

  return result;
}

function generateNextLine(state, level) {
  return '\n' + common.repeat(' ', state.indent * level);
}

function testImplicitResolving(state, str) {
  var index, length, type;

  for (index = 0, length = state.implicitTypes.length; index < length; index += 1) {
    type = state.implicitTypes[index];

    if (type.resolve(str)) {
      return true;
    }
  }

  return false;
}

// [33] s-white ::= s-space | s-tab
function isWhitespace(c) {
  return c === CHAR_SPACE || c === CHAR_TAB;
}

// Returns true if the character can be printed without escaping.
// From YAML 1.2: "any allowed characters known to be non-printable
// should also be escaped. [However,] This isn’t mandatory"
// Derived from nb-char - \t - #x85 - #xA0 - #x2028 - #x2029.
function isPrintable(c) {
  return  (0x00020 <= c && c <= 0x00007E)
      || ((0x000A1 <= c && c <= 0x00D7FF) && c !== 0x2028 && c !== 0x2029)
      || ((0x0E000 <= c && c <= 0x00FFFD) && c !== CHAR_BOM)
      ||  (0x10000 <= c && c <= 0x10FFFF);
}

// [34] ns-char ::= nb-char - s-white
// [27] nb-char ::= c-printable - b-char - c-byte-order-mark
// [26] b-char  ::= b-line-feed | b-carriage-return
// Including s-white (for some reason, examples doesn't match specs in this aspect)
// ns-char ::= c-printable - b-line-feed - b-carriage-return - c-byte-order-mark
function isNsCharOrWhitespace(c) {
  return isPrintable(c)
    && c !== CHAR_BOM
    // - b-char
    && c !== CHAR_CARRIAGE_RETURN
    && c !== CHAR_LINE_FEED;
}

// [127]  ns-plain-safe(c) ::= c = flow-out  ⇒ ns-plain-safe-out
//                             c = flow-in   ⇒ ns-plain-safe-in
//                             c = block-key ⇒ ns-plain-safe-out
//                             c = flow-key  ⇒ ns-plain-safe-in
// [128] ns-plain-safe-out ::= ns-char
// [129]  ns-plain-safe-in ::= ns-char - c-flow-indicator
// [130]  ns-plain-char(c) ::=  ( ns-plain-safe(c) - “:” - “#” )
//                            | ( /* An ns-char preceding */ “#” )
//                            | ( “:” /* Followed by an ns-plain-safe(c) */ )
function isPlainSafe(c, prev, inblock) {
  var cIsNsCharOrWhitespace = isNsCharOrWhitespace(c);
  var cIsNsChar = cIsNsCharOrWhitespace && !isWhitespace(c);
  return (
    // ns-plain-safe
    inblock ? // c = flow-in
      cIsNsCharOrWhitespace
      : cIsNsCharOrWhitespace
        // - c-flow-indicator
        && c !== CHAR_COMMA
        && c !== CHAR_LEFT_SQUARE_BRACKET
        && c !== CHAR_RIGHT_SQUARE_BRACKET
        && c !== CHAR_LEFT_CURLY_BRACKET
        && c !== CHAR_RIGHT_CURLY_BRACKET
  )
    // ns-plain-char
    && c !== CHAR_SHARP // false on '#'
    && !(prev === CHAR_COLON && !cIsNsChar) // false on ': '
    || (isNsCharOrWhitespace(prev) && !isWhitespace(prev) && c === CHAR_SHARP) // change to true on '[^ ]#'
    || (prev === CHAR_COLON && cIsNsChar); // change to true on ':[^ ]'
}

// Simplified test for values allowed as the first character in plain style.
function isPlainSafeFirst(c) {
  // Uses a subset of ns-char - c-indicator
  // where ns-char = nb-char - s-white.
  // No support of ( ( “?” | “:” | “-” ) /* Followed by an ns-plain-safe(c)) */ ) part
  return isPrintable(c) && c !== CHAR_BOM
    && !isWhitespace(c) // - s-white
    // - (c-indicator ::=
    // “-” | “?” | “:” | “,” | “[” | “]” | “{” | “}”
    && c !== CHAR_MINUS
    && c !== CHAR_QUESTION
    && c !== CHAR_COLON
    && c !== CHAR_COMMA
    && c !== CHAR_LEFT_SQUARE_BRACKET
    && c !== CHAR_RIGHT_SQUARE_BRACKET
    && c !== CHAR_LEFT_CURLY_BRACKET
    && c !== CHAR_RIGHT_CURLY_BRACKET
    // | “#” | “&” | “*” | “!” | “|” | “=” | “>” | “'” | “"”
    && c !== CHAR_SHARP
    && c !== CHAR_AMPERSAND
    && c !== CHAR_ASTERISK
    && c !== CHAR_EXCLAMATION
    && c !== CHAR_VERTICAL_LINE
    && c !== CHAR_EQUALS
    && c !== CHAR_GREATER_THAN
    && c !== CHAR_SINGLE_QUOTE
    && c !== CHAR_DOUBLE_QUOTE
    // | “%” | “@” | “`”)
    && c !== CHAR_PERCENT
    && c !== CHAR_COMMERCIAL_AT
    && c !== CHAR_GRAVE_ACCENT;
}

// Simplified test for values allowed as the last character in plain style.
function isPlainSafeLast(c) {
  // just not whitespace or colon, it will be checked to be plain character later
  return !isWhitespace(c) && c !== CHAR_COLON;
}

// Same as 'string'.codePointAt(pos), but works in older browsers.
function codePointAt(string, pos) {
  var first = string.charCodeAt(pos), second;
  if (first >= 0xD800 && first <= 0xDBFF && pos + 1 < string.length) {
    second = string.charCodeAt(pos + 1);
    if (second >= 0xDC00 && second <= 0xDFFF) {
      // https://mathiasbynens.be/notes/javascript-encoding#surrogate-formulae
      return (first - 0xD800) * 0x400 + second - 0xDC00 + 0x10000;
    }
  }
  return first;
}

// Determines whether block indentation indicator is required.
function needIndentIndicator(string) {
  var leadingSpaceRe = /^\n* /;
  return leadingSpaceRe.test(string);
}

var STYLE_PLAIN   = 1,
    STYLE_SINGLE  = 2,
    STYLE_LITERAL = 3,
    STYLE_FOLDED  = 4,
    STYLE_DOUBLE  = 5;

// Determines which scalar styles are possible and returns the preferred style.
// lineWidth = -1 => no limit.
// Pre-conditions: str.length > 0.
// Post-conditions:
//    STYLE_PLAIN or STYLE_SINGLE => no \n are in the string.
//    STYLE_LITERAL => no lines are suitable for folding (or lineWidth is -1).
//    STYLE_FOLDED => a line > lineWidth and can be folded (and lineWidth != -1).
function chooseScalarStyle(string, singleLineOnly, indentPerLevel, lineWidth,
  testAmbiguousType, quotingType, forceQuotes, inblock) {

  var i;
  var char = 0;
  var prevChar = null;
  var hasLineBreak = false;
  var hasFoldableLine = false; // only checked if shouldTrackWidth
  var shouldTrackWidth = lineWidth !== -1;
  var previousLineBreak = -1; // count the first line correctly
  var plain = isPlainSafeFirst(codePointAt(string, 0))
          && isPlainSafeLast(codePointAt(string, string.length - 1));

  if (singleLineOnly || forceQuotes) {
    // Case: no block styles.
    // Check for disallowed characters to rule out plain and single.
    for (i = 0; i < string.length; char >= 0x10000 ? i += 2 : i++) {
      char = codePointAt(string, i);
      if (!isPrintable(char)) {
        return STYLE_DOUBLE;
      }
      plain = plain && isPlainSafe(char, prevChar, inblock);
      prevChar = char;
    }
  } else {
    // Case: block styles permitted.
    for (i = 0; i < string.length; char >= 0x10000 ? i += 2 : i++) {
      char = codePointAt(string, i);
      if (char === CHAR_LINE_FEED) {
        hasLineBreak = true;
        // Check if any line can be folded.
        if (shouldTrackWidth) {
          hasFoldableLine = hasFoldableLine ||
            // Foldable line = too long, and not more-indented.
            (i - previousLineBreak - 1 > lineWidth &&
             string[previousLineBreak + 1] !== ' ');
          previousLineBreak = i;
        }
      } else if (!isPrintable(char)) {
        return STYLE_DOUBLE;
      }
      plain = plain && isPlainSafe(char, prevChar, inblock);
      prevChar = char;
    }
    // in case the end is missing a \n
    hasFoldableLine = hasFoldableLine || (shouldTrackWidth &&
      (i - previousLineBreak - 1 > lineWidth &&
       string[previousLineBreak + 1] !== ' '));
  }
  // Although every style can represent \n without escaping, prefer block styles
  // for multiline, since they're more readable and they don't add empty lines.
  // Also prefer folding a super-long line.
  if (!hasLineBreak && !hasFoldableLine) {
    // Strings interpretable as another type have to be quoted;
    // e.g. the string 'true' vs. the boolean true.
    if (plain && !forceQuotes && !testAmbiguousType(string)) {
      return STYLE_PLAIN;
    }
    return quotingType === QUOTING_TYPE_DOUBLE ? STYLE_DOUBLE : STYLE_SINGLE;
  }
  // Edge case: block indentation indicator can only have one digit.
  if (indentPerLevel > 9 && needIndentIndicator(string)) {
    return STYLE_DOUBLE;
  }
  // At this point we know block styles are valid.
  // Prefer literal style unless we want to fold.
  if (!forceQuotes) {
    return hasFoldableLine ? STYLE_FOLDED : STYLE_LITERAL;
  }
  return quotingType === QUOTING_TYPE_DOUBLE ? STYLE_DOUBLE : STYLE_SINGLE;
}

// Note: line breaking/folding is implemented for only the folded style.
// NB. We drop the last trailing newline (if any) of a returned block scalar
//  since the dumper adds its own newline. This always works:
//    • No ending newline => unaffected; already using strip "-" chomping.
//    • Ending newline    => removed then restored.
//  Importantly, this keeps the "+" chomp indicator from gaining an extra line.
function writeScalar(state, string, level, iskey, inblock) {
  state.dump = (function () {
    if (string.length === 0) {
      return state.quotingType === QUOTING_TYPE_DOUBLE ? '""' : "''";
    }
    if (!state.noCompatMode) {
      if (DEPRECATED_BOOLEANS_SYNTAX.indexOf(string) !== -1 || DEPRECATED_BASE60_SYNTAX.test(string)) {
        return state.quotingType === QUOTING_TYPE_DOUBLE ? ('"' + string + '"') : ("'" + string + "'");
      }
    }

    var indent = state.indent * Math.max(1, level); // no 0-indent scalars
    // As indentation gets deeper, let the width decrease monotonically
    // to the lower bound min(state.lineWidth, 40).
    // Note that this implies
    //  state.lineWidth ≤ 40 + state.indent: width is fixed at the lower bound.
    //  state.lineWidth > 40 + state.indent: width decreases until the lower bound.
    // This behaves better than a constant minimum width which disallows narrower options,
    // or an indent threshold which causes the width to suddenly increase.
    var lineWidth = state.lineWidth === -1
      ? -1 : Math.max(Math.min(state.lineWidth, 40), state.lineWidth - indent);

    // Without knowing if keys are implicit/explicit, assume implicit for safety.
    var singleLineOnly = iskey
      // No block styles in flow mode.
      || (state.flowLevel > -1 && level >= state.flowLevel);
    function testAmbiguity(string) {
      return testImplicitResolving(state, string);
    }

    switch (chooseScalarStyle(string, singleLineOnly, state.indent, lineWidth,
      testAmbiguity, state.quotingType, state.forceQuotes && !iskey, inblock)) {

      case STYLE_PLAIN:
        return string;
      case STYLE_SINGLE:
        return "'" + string.replace(/'/g, "''") + "'";
      case STYLE_LITERAL:
        return '|' + blockHeader(string, state.indent)
          + dropEndingNewline(indentString(string, indent));
      case STYLE_FOLDED:
        return '>' + blockHeader(string, state.indent)
          + dropEndingNewline(indentString(foldString(string, lineWidth), indent));
      case STYLE_DOUBLE:
        return '"' + escapeString(string) + '"';
      default:
        throw new exception('impossible error: invalid scalar style');
    }
  }());
}

// Pre-conditions: string is valid for a block scalar, 1 <= indentPerLevel <= 9.
function blockHeader(string, indentPerLevel) {
  var indentIndicator = needIndentIndicator(string) ? String(indentPerLevel) : '';

  // note the special case: the string '\n' counts as a "trailing" empty line.
  var clip =          string[string.length - 1] === '\n';
  var keep = clip && (string[string.length - 2] === '\n' || string === '\n');
  var chomp = keep ? '+' : (clip ? '' : '-');

  return indentIndicator + chomp + '\n';
}

// (See the note for writeScalar.)
function dropEndingNewline(string) {
  return string[string.length - 1] === '\n' ? string.slice(0, -1) : string;
}

// Note: a long line without a suitable break point will exceed the width limit.
// Pre-conditions: every char in str isPrintable, str.length > 0, width > 0.
function foldString(string, width) {
  // In folded style, $k$ consecutive newlines output as $k+1$ newlines—
  // unless they're before or after a more-indented line, or at the very
  // beginning or end, in which case $k$ maps to $k$.
  // Therefore, parse each chunk as newline(s) followed by a content line.
  var lineRe = /(\n+)([^\n]*)/g;

  // first line (possibly an empty line)
  var result = (function () {
    var nextLF = string.indexOf('\n');
    nextLF = nextLF !== -1 ? nextLF : string.length;
    lineRe.lastIndex = nextLF;
    return foldLine(string.slice(0, nextLF), width);
  }());
  // If we haven't reached the first content line yet, don't add an extra \n.
  var prevMoreIndented = string[0] === '\n' || string[0] === ' ';
  var moreIndented;

  // rest of the lines
  var match;
  while ((match = lineRe.exec(string))) {
    var prefix = match[1], line = match[2];
    moreIndented = (line[0] === ' ');
    result += prefix
      + (!prevMoreIndented && !moreIndented && line !== ''
        ? '\n' : '')
      + foldLine(line, width);
    prevMoreIndented = moreIndented;
  }

  return result;
}

// Greedy line breaking.
// Picks the longest line under the limit each time,
// otherwise settles for the shortest line over the limit.
// NB. More-indented lines *cannot* be folded, as that would add an extra \n.
function foldLine(line, width) {
  if (line === '' || line[0] === ' ') return line;

  // Since a more-indented line adds a \n, breaks can't be followed by a space.
  var breakRe = / [^ ]/g; // note: the match index will always be <= length-2.
  var match;
  // start is an inclusive index. end, curr, and next are exclusive.
  var start = 0, end, curr = 0, next = 0;
  var result = '';

  // Invariants: 0 <= start <= length-1.
  //   0 <= curr <= next <= max(0, length-2). curr - start <= width.
  // Inside the loop:
  //   A match implies length >= 2, so curr and next are <= length-2.
  while ((match = breakRe.exec(line))) {
    next = match.index;
    // maintain invariant: curr - start <= width
    if (next - start > width) {
      end = (curr > start) ? curr : next; // derive end <= length-2
      result += '\n' + line.slice(start, end);
      // skip the space that was output as \n
      start = end + 1;                    // derive start <= length-1
    }
    curr = next;
  }

  // By the invariants, start <= length-1, so there is something left over.
  // It is either the whole string or a part starting from non-whitespace.
  result += '\n';
  // Insert a break if the remainder is too long and there is a break available.
  if (line.length - start > width && curr > start) {
    result += line.slice(start, curr) + '\n' + line.slice(curr + 1);
  } else {
    result += line.slice(start);
  }

  return result.slice(1); // drop extra \n joiner
}

// Escapes a double-quoted string.
function escapeString(string) {
  var result = '';
  var char = 0;
  var escapeSeq;

  for (var i = 0; i < string.length; char >= 0x10000 ? i += 2 : i++) {
    char = codePointAt(string, i);
    escapeSeq = ESCAPE_SEQUENCES[char];

    if (!escapeSeq && isPrintable(char)) {
      result += string[i];
      if (char >= 0x10000) result += string[i + 1];
    } else {
      result += escapeSeq || encodeHex(char);
    }
  }

  return result;
}

function writeFlowSequence(state, level, object) {
  var _result = '',
      _tag    = state.tag,
      index,
      length,
      value;

  for (index = 0, length = object.length; index < length; index += 1) {
    value = object[index];

    if (state.replacer) {
      value = state.replacer.call(object, String(index), value);
    }

    // Write only valid elements, put null instead of invalid elements.
    if (writeNode(state, level, value, false, false) ||
        (typeof value === 'undefined' &&
         writeNode(state, level, null, false, false))) {

      if (_result !== '') _result += ',' + (!state.condenseFlow ? ' ' : '');
      _result += state.dump;
    }
  }

  state.tag = _tag;
  state.dump = '[' + _result + ']';
}

function writeBlockSequence(state, level, object, compact) {
  var _result = '',
      _tag    = state.tag,
      index,
      length,
      value;

  for (index = 0, length = object.length; index < length; index += 1) {
    value = object[index];

    if (state.replacer) {
      value = state.replacer.call(object, String(index), value);
    }

    // Write only valid elements, put null instead of invalid elements.
    if (writeNode(state, level + 1, value, true, true, false, true) ||
        (typeof value === 'undefined' &&
         writeNode(state, level + 1, null, true, true, false, true))) {

      if (!compact || _result !== '') {
        _result += generateNextLine(state, level);
      }

      if (state.dump && CHAR_LINE_FEED === state.dump.charCodeAt(0)) {
        _result += '-';
      } else {
        _result += '- ';
      }

      _result += state.dump;
    }
  }

  state.tag = _tag;
  state.dump = _result || '[]'; // Empty sequence if no valid values.
}

function writeFlowMapping(state, level, object) {
  var _result       = '',
      _tag          = state.tag,
      objectKeyList = Object.keys(object),
      index,
      length,
      objectKey,
      objectValue,
      pairBuffer;

  for (index = 0, length = objectKeyList.length; index < length; index += 1) {

    pairBuffer = '';
    if (_result !== '') pairBuffer += ', ';

    if (state.condenseFlow) pairBuffer += '"';

    objectKey = objectKeyList[index];
    objectValue = object[objectKey];

    if (state.replacer) {
      objectValue = state.replacer.call(object, objectKey, objectValue);
    }

    if (!writeNode(state, level, objectKey, false, false)) {
      continue; // Skip this pair because of invalid key;
    }

    if (state.dump.length > 1024) pairBuffer += '? ';

    pairBuffer += state.dump + (state.condenseFlow ? '"' : '') + ':' + (state.condenseFlow ? '' : ' ');

    if (!writeNode(state, level, objectValue, false, false)) {
      continue; // Skip this pair because of invalid value.
    }

    pairBuffer += state.dump;

    // Both key and value are valid.
    _result += pairBuffer;
  }

  state.tag = _tag;
  state.dump = '{' + _result + '}';
}

function writeBlockMapping(state, level, object, compact) {
  var _result       = '',
      _tag          = state.tag,
      objectKeyList = Object.keys(object),
      index,
      length,
      objectKey,
      objectValue,
      explicitPair,
      pairBuffer;

  // Allow sorting keys so that the output file is deterministic
  if (state.sortKeys === true) {
    // Default sorting
    objectKeyList.sort();
  } else if (typeof state.sortKeys === 'function') {
    // Custom sort function
    objectKeyList.sort(state.sortKeys);
  } else if (state.sortKeys) {
    // Something is wrong
    throw new exception('sortKeys must be a boolean or a function');
  }

  for (index = 0, length = objectKeyList.length; index < length; index += 1) {
    pairBuffer = '';

    if (!compact || _result !== '') {
      pairBuffer += generateNextLine(state, level);
    }

    objectKey = objectKeyList[index];
    objectValue = object[objectKey];

    if (state.replacer) {
      objectValue = state.replacer.call(object, objectKey, objectValue);
    }

    if (!writeNode(state, level + 1, objectKey, true, true, true)) {
      continue; // Skip this pair because of invalid key.
    }

    explicitPair = (state.tag !== null && state.tag !== '?') ||
                   (state.dump && state.dump.length > 1024);

    if (explicitPair) {
      if (state.dump && CHAR_LINE_FEED === state.dump.charCodeAt(0)) {
        pairBuffer += '?';
      } else {
        pairBuffer += '? ';
      }
    }

    pairBuffer += state.dump;

    if (explicitPair) {
      pairBuffer += generateNextLine(state, level);
    }

    if (!writeNode(state, level + 1, objectValue, true, explicitPair)) {
      continue; // Skip this pair because of invalid value.
    }

    if (state.dump && CHAR_LINE_FEED === state.dump.charCodeAt(0)) {
      pairBuffer += ':';
    } else {
      pairBuffer += ': ';
    }

    pairBuffer += state.dump;

    // Both key and value are valid.
    _result += pairBuffer;
  }

  state.tag = _tag;
  state.dump = _result || '{}'; // Empty mapping if no valid pairs.
}

function detectType(state, object, explicit) {
  var _result, typeList, index, length, type, style;

  typeList = explicit ? state.explicitTypes : state.implicitTypes;

  for (index = 0, length = typeList.length; index < length; index += 1) {
    type = typeList[index];

    if ((type.instanceOf  || type.predicate) &&
        (!type.instanceOf || ((typeof object === 'object') && (object instanceof type.instanceOf))) &&
        (!type.predicate  || type.predicate(object))) {

      if (explicit) {
        if (type.multi && type.representName) {
          state.tag = type.representName(object);
        } else {
          state.tag = type.tag;
        }
      } else {
        state.tag = '?';
      }

      if (type.represent) {
        style = state.styleMap[type.tag] || type.defaultStyle;

        if (_toString.call(type.represent) === '[object Function]') {
          _result = type.represent(object, style);
        } else if (_hasOwnProperty.call(type.represent, style)) {
          _result = type.represent[style](object, style);
        } else {
          throw new exception('!<' + type.tag + '> tag resolver accepts not "' + style + '" style');
        }

        state.dump = _result;
      }

      return true;
    }
  }

  return false;
}

// Serializes `object` and writes it to global `result`.
// Returns true on success, or false on invalid object.
//
function writeNode(state, level, object, block, compact, iskey, isblockseq) {
  state.tag = null;
  state.dump = object;

  if (!detectType(state, object, false)) {
    detectType(state, object, true);
  }

  var type = _toString.call(state.dump);
  var inblock = block;
  var tagStr;

  if (block) {
    block = (state.flowLevel < 0 || state.flowLevel > level);
  }

  var objectOrArray = type === '[object Object]' || type === '[object Array]',
      duplicateIndex,
      duplicate;

  if (objectOrArray) {
    duplicateIndex = state.duplicates.indexOf(object);
    duplicate = duplicateIndex !== -1;
  }

  if ((state.tag !== null && state.tag !== '?') || duplicate || (state.indent !== 2 && level > 0)) {
    compact = false;
  }

  if (duplicate && state.usedDuplicates[duplicateIndex]) {
    state.dump = '*ref_' + duplicateIndex;
  } else {
    if (objectOrArray && duplicate && !state.usedDuplicates[duplicateIndex]) {
      state.usedDuplicates[duplicateIndex] = true;
    }
    if (type === '[object Object]') {
      if (block && (Object.keys(state.dump).length !== 0)) {
        writeBlockMapping(state, level, state.dump, compact);
        if (duplicate) {
          state.dump = '&ref_' + duplicateIndex + state.dump;
        }
      } else {
        writeFlowMapping(state, level, state.dump);
        if (duplicate) {
          state.dump = '&ref_' + duplicateIndex + ' ' + state.dump;
        }
      }
    } else if (type === '[object Array]') {
      if (block && (state.dump.length !== 0)) {
        if (state.noArrayIndent && !isblockseq && level > 0) {
          writeBlockSequence(state, level - 1, state.dump, compact);
        } else {
          writeBlockSequence(state, level, state.dump, compact);
        }
        if (duplicate) {
          state.dump = '&ref_' + duplicateIndex + state.dump;
        }
      } else {
        writeFlowSequence(state, level, state.dump);
        if (duplicate) {
          state.dump = '&ref_' + duplicateIndex + ' ' + state.dump;
        }
      }
    } else if (type === '[object String]') {
      if (state.tag !== '?') {
        writeScalar(state, state.dump, level, iskey, inblock);
      }
    } else if (type === '[object Undefined]') {
      return false;
    } else {
      if (state.skipInvalid) return false;
      throw new exception('unacceptable kind of an object to dump ' + type);
    }

    if (state.tag !== null && state.tag !== '?') {
      // Need to encode all characters except those allowed by the spec:
      //
      // [35] ns-dec-digit    ::=  [#x30-#x39] /* 0-9 */
      // [36] ns-hex-digit    ::=  ns-dec-digit
      //                         | [#x41-#x46] /* A-F */ | [#x61-#x66] /* a-f */
      // [37] ns-ascii-letter ::=  [#x41-#x5A] /* A-Z */ | [#x61-#x7A] /* a-z */
      // [38] ns-word-char    ::=  ns-dec-digit | ns-ascii-letter | “-”
      // [39] ns-uri-char     ::=  “%” ns-hex-digit ns-hex-digit | ns-word-char | “#”
      //                         | “;” | “/” | “?” | “:” | “@” | “&” | “=” | “+” | “$” | “,”
      //                         | “_” | “.” | “!” | “~” | “*” | “'” | “(” | “)” | “[” | “]”
      //
      // Also need to encode '!' because it has special meaning (end of tag prefix).
      //
      tagStr = encodeURI(
        state.tag[0] === '!' ? state.tag.slice(1) : state.tag
      ).replace(/!/g, '%21');

      if (state.tag[0] === '!') {
        tagStr = '!' + tagStr;
      } else if (tagStr.slice(0, 18) === 'tag:yaml.org,2002:') {
        tagStr = '!!' + tagStr.slice(18);
      } else {
        tagStr = '!<' + tagStr + '>';
      }

      state.dump = tagStr + ' ' + state.dump;
    }
  }

  return true;
}

function getDuplicateReferences(object, state) {
  var objects = [],
      duplicatesIndexes = [],
      index,
      length;

  inspectNode(object, objects, duplicatesIndexes);

  for (index = 0, length = duplicatesIndexes.length; index < length; index += 1) {
    state.duplicates.push(objects[duplicatesIndexes[index]]);
  }
  state.usedDuplicates = new Array(length);
}

function inspectNode(object, objects, duplicatesIndexes) {
  var objectKeyList,
      index,
      length;

  if (object !== null && typeof object === 'object') {
    index = objects.indexOf(object);
    if (index !== -1) {
      if (duplicatesIndexes.indexOf(index) === -1) {
        duplicatesIndexes.push(index);
      }
    } else {
      objects.push(object);

      if (Array.isArray(object)) {
        for (index = 0, length = object.length; index < length; index += 1) {
          inspectNode(object[index], objects, duplicatesIndexes);
        }
      } else {
        objectKeyList = Object.keys(object);

        for (index = 0, length = objectKeyList.length; index < length; index += 1) {
          inspectNode(object[objectKeyList[index]], objects, duplicatesIndexes);
        }
      }
    }
  }
}

function dump$1(input, options) {
  options = options || {};

  var state = new State(options);

  if (!state.noRefs) getDuplicateReferences(input, state);

  var value = input;

  if (state.replacer) {
    value = state.replacer.call({ '': value }, '', value);
  }

  if (writeNode(state, 0, value, true, true)) return state.dump + '\n';

  return '';
}

var dump_1 = dump$1;

var dumper = {
	dump: dump_1
};

function renamed(from, to) {
  return function () {
    throw new Error('Function yaml.' + from + ' is removed in js-yaml 4. ' +
      'Use yaml.' + to + ' instead, which is now safe by default.');
  };
}


var Type                = type;
var Schema              = schema;
var FAILSAFE_SCHEMA     = failsafe;
var JSON_SCHEMA         = json;
var CORE_SCHEMA         = core;
var DEFAULT_SCHEMA      = _default;
var load                = loader.load;
var loadAll             = loader.loadAll;
var dump                = dumper.dump;
var YAMLException       = exception;

// Re-export all types in case user wants to create custom schema
var types = {
  binary:    binary,
  float:     float,
  map:       map,
  null:      _null,
  pairs:     pairs,
  set:       set,
  timestamp: timestamp,
  bool:      bool,
  int:       int,
  merge:     merge,
  omap:      omap,
  seq:       seq,
  str:       str
};

// Removed functions from JS-YAML 3.0.x
var safeLoad            = renamed('safeLoad', 'load');
var safeLoadAll         = renamed('safeLoadAll', 'loadAll');
var safeDump            = renamed('safeDump', 'dump');

var jsYaml = {
	Type: Type,
	Schema: Schema,
	FAILSAFE_SCHEMA: FAILSAFE_SCHEMA,
	JSON_SCHEMA: JSON_SCHEMA,
	CORE_SCHEMA: CORE_SCHEMA,
	DEFAULT_SCHEMA: DEFAULT_SCHEMA,
	load: load,
	loadAll: loadAll,
	dump: dump,
	YAMLException: YAMLException,
	types: types,
	safeLoad: safeLoad,
	safeLoadAll: safeLoadAll,
	safeDump: safeDump
};

const {defineComponent:_defineComponent$w} = await importShared('vue');

const {createTextVNode:_createTextVNode$w,resolveComponent:_resolveComponent$w,withCtx:_withCtx$w,createVNode:_createVNode$w,unref:_unref$q,openBlock:_openBlock$w,createBlock:_createBlock$w} = await importShared('vue');
const _sfc_main$w = /* @__PURE__ */ _defineComponent$w({
  __name: "ShowYamlDialog",
  props: {
    content: {
      type: String,
      required: true
    },
    placeholder: String
  },
  emits: ["close", "copyToClipboard"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const readOnlyEditorOptions = {
      readOnly: true,
      enableBasicAutocompletion: true,
      enableSnippets: true,
      enableLiveAutocompletion: true,
      showLineNumbers: true,
      tabSize: 2
    };
    const emit = __emit;
    return (_ctx, _cache) => {
      const _component_v_card_title = _resolveComponent$w("v-card-title");
      const _component_v_card_text = _resolveComponent$w("v-card-text");
      const _component_v_spacer = _resolveComponent$w("v-spacer");
      const _component_v_btn = _resolveComponent$w("v-btn");
      const _component_v_card_actions = _resolveComponent$w("v-card-actions");
      const _component_v_card = _resolveComponent$w("v-card");
      const _component_v_dialog = _resolveComponent$w("v-dialog");
      return _openBlock$w(), _createBlock$w(_component_v_dialog, {
        "model-value": true,
        "max-width": "40rem",
        "onUpdate:modelValue": _cache[2] || (_cache[2] = ($event) => emit("close"))
      }, {
        default: _withCtx$w(() => [
          _createVNode$w(_component_v_card, null, {
            default: _withCtx$w(() => [
              _createVNode$w(_component_v_card_title, { class: "headline" }, {
                default: _withCtx$w(() => _cache[3] || (_cache[3] = [
                  _createTextVNode$w("YAML 配置")
                ])),
                _: 1
              }),
              _createVNode$w(_component_v_card_text, { style: { "max-height": "600px", "overflow-y": "auto" } }, {
                default: _withCtx$w(() => [
                  _createVNode$w(_unref$q(VAceEditor), {
                    value: props.content,
                    lang: "yaml",
                    theme: "monokai",
                    options: readOnlyEditorOptions,
                    placeholder: __props.placeholder,
                    style: { "height": "30rem", "width": "100%", "margin-bottom": "16px" }
                  }, null, 8, ["value", "placeholder"])
                ]),
                _: 1
              }),
              _createVNode$w(_component_v_card_actions, null, {
                default: _withCtx$w(() => [
                  _createVNode$w(_component_v_spacer),
                  _createVNode$w(_component_v_btn, {
                    color: "primary",
                    onClick: _cache[0] || (_cache[0] = ($event) => emit("copyToClipboard", __props.content))
                  }, {
                    default: _withCtx$w(() => _cache[4] || (_cache[4] = [
                      _createTextVNode$w("复制")
                    ])),
                    _: 1
                  }),
                  _createVNode$w(_component_v_btn, {
                    color: "primary",
                    onClick: _cache[1] || (_cache[1] = ($event) => emit("close"))
                  }, {
                    default: _withCtx$w(() => _cache[5] || (_cache[5] = [
                      _createTextVNode$w("关闭")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _: 1
      });
    };
  }
});

const {defineComponent:_defineComponent$v} = await importShared('vue');

const {createTextVNode:_createTextVNode$v,resolveComponent:_resolveComponent$v,withCtx:_withCtx$v,createVNode:_createVNode$v,createElementVNode:_createElementVNode$o,renderList:_renderList$a,Fragment:_Fragment$b,openBlock:_openBlock$v,createElementBlock:_createElementBlock$c,toDisplayString:_toDisplayString$s,createBlock:_createBlock$v,createCommentVNode:_createCommentVNode$r} = await importShared('vue');

const _hoisted_1$l = { class: "d-flex align-center justify-space-between mb-2" };
const _hoisted_2$f = {
  key: 0,
  class: "text-caption text-grey text-center py-2"
};
const {ref: ref$l,toRaw: toRaw$9,onMounted: onMounted$1} = await importShared('vue');

const _sfc_main$v = /* @__PURE__ */ _defineComponent$v({
  __name: "DataVisibilityDialog",
  props: {
    meta: {
      type: Object,
      required: true
    },
    api: {
      type: Object,
      required: true
    },
    endpoint: {
      type: String,
      required: true
    },
    region: String,
    presetIdentifiers: {
      type: Array,
      required: true
    }
  },
  emits: ["refresh", "show-snackbar", "show-error", "close"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const loading = ref$l(false);
    const invisibleTo = ref$l(structuredClone(toRaw$9(props.meta?.invisible_to) || []));
    const selectedPresets = ref$l([]);
    const customExpressions = ref$l([]);
    const expressionTemplate = (id) => `identifier == '${id}'`;
    const expressionRegex = /^identifier == '(.+)'$/;
    onMounted$1(() => {
      parseInvisibleTo();
    });
    function parseInvisibleTo() {
      const presets = [];
      const custom = [];
      const currentInvisible = invisibleTo.value || [];
      currentInvisible.forEach((expr) => {
        const match = expr.match(expressionRegex);
        if (match && props.presetIdentifiers.includes(match[1])) {
          presets.push(match[1]);
        } else {
          custom.push(expr);
        }
      });
      selectedPresets.value = presets;
      customExpressions.value = custom;
    }
    function addCustomExpression() {
      customExpressions.value.push("");
    }
    function removeCustomExpression(index) {
      customExpressions.value.splice(index, 1);
    }
    async function updateDataVisibility() {
      let newInvisibleTo;
      newInvisibleTo = [
        ...selectedPresets.value.map((id) => expressionTemplate(id)),
        ...customExpressions.value.filter((e) => e.trim() !== "")
      ];
      invisibleTo.value = newInvisibleTo;
      loading.value = true;
      try {
        const meta = structuredClone(toRaw$9(props.meta));
        meta.invisible_to = invisibleTo.value;
        const result = await props.api.patch(props.endpoint, meta);
        if (props.region) emit("refresh", [props.region]);
        if (result?.success) {
          emit("show-snackbar", {
            show: true,
            message: "可见性配置更新成功",
            color: "success"
          });
          emit("close");
        } else {
          emit("show-error", "更新可见性配置失败: " + (result.message || "未知错误"));
          emit("show-snackbar", {
            show: true,
            message: "更新可见性配置失败",
            color: "error"
          });
        }
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", err.message || "更新可见性配置失败");
        }
      } finally {
        loading.value = false;
      }
    }
    return (_ctx, _cache) => {
      const _component_v_card_title = _resolveComponent$v("v-card-title");
      const _component_v_alert = _resolveComponent$v("v-alert");
      const _component_v_chip = _resolveComponent$v("v-chip");
      const _component_v_chip_group = _resolveComponent$v("v-chip-group");
      const _component_v_divider = _resolveComponent$v("v-divider");
      const _component_v_btn = _resolveComponent$v("v-btn");
      const _component_v_text_field = _resolveComponent$v("v-text-field");
      const _component_v_card_text = _resolveComponent$v("v-card-text");
      const _component_v_spacer = _resolveComponent$v("v-spacer");
      const _component_v_card_actions = _resolveComponent$v("v-card-actions");
      const _component_v_card = _resolveComponent$v("v-card");
      const _component_v_dialog = _resolveComponent$v("v-dialog");
      return _openBlock$v(), _createBlock$v(_component_v_dialog, { "max-width": "40rem" }, {
        default: _withCtx$v(() => [
          _createVNode$v(_component_v_card, null, {
            default: _withCtx$v(() => [
              _createVNode$v(_component_v_card_title, null, {
                default: _withCtx$v(() => _cache[2] || (_cache[2] = [
                  _createTextVNode$v(" 限制可见性 ")
                ])),
                _: 1
              }),
              _createVNode$v(_component_v_card_text, null, {
                default: _withCtx$v(() => [
                  _createVNode$v(_component_v_alert, {
                    type: "info",
                    variant: "tonal",
                    class: "mb-4",
                    density: "compact"
                  }, {
                    default: _withCtx$v(() => _cache[3] || (_cache[3] = [
                      _createTextVNode$v(" 配置数据项对哪些设备不可见。勾选预设设备或输入自定义表达式 (simpleeval)。 ")
                    ])),
                    _: 1
                  }),
                  _cache[6] || (_cache[6] = _createElementVNode$o("div", { class: "text-subtitle-1 mb-2" }, "预设设备", -1)),
                  _createVNode$v(_component_v_chip_group, {
                    modelValue: selectedPresets.value,
                    "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => selectedPresets.value = $event),
                    column: "",
                    multiple: "",
                    filter: "",
                    "selected-class": "text-primary"
                  }, {
                    default: _withCtx$v(() => [
                      (_openBlock$v(true), _createElementBlock$c(_Fragment$b, null, _renderList$a(__props.presetIdentifiers, (id) => {
                        return _openBlock$v(), _createBlock$v(_component_v_chip, {
                          key: id,
                          value: id,
                          variant: "outlined",
                          filter: ""
                        }, {
                          default: _withCtx$v(() => [
                            _createTextVNode$v(_toDisplayString$s(id), 1)
                          ]),
                          _: 2
                        }, 1032, ["value"]);
                      }), 128))
                    ]),
                    _: 1
                  }, 8, ["modelValue"]),
                  _createVNode$v(_component_v_divider, { class: "my-4" }),
                  _createElementVNode$o("div", _hoisted_1$l, [
                    _cache[5] || (_cache[5] = _createElementVNode$o("div", { class: "text-subtitle-1" }, "自定义表达式", -1)),
                    _createVNode$v(_component_v_btn, {
                      size: "small",
                      variant: "text",
                      color: "primary",
                      "prepend-icon": "mdi-plus",
                      onClick: addCustomExpression
                    }, {
                      default: _withCtx$v(() => _cache[4] || (_cache[4] = [
                        _createTextVNode$v(" 添加 ")
                      ])),
                      _: 1
                    })
                  ]),
                  (_openBlock$v(true), _createElementBlock$c(_Fragment$b, null, _renderList$a(customExpressions.value.keys(), (index) => {
                    return _openBlock$v(), _createElementBlock$c("div", {
                      key: index,
                      class: "d-flex align-center mb-2"
                    }, [
                      _createVNode$v(_component_v_text_field, {
                        modelValue: customExpressions.value[index],
                        "onUpdate:modelValue": ($event) => customExpressions.value[index] = $event,
                        label: "表达式",
                        variant: "outlined",
                        density: "compact",
                        "hide-details": "",
                        class: "flex-grow-1"
                      }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                      _createVNode$v(_component_v_btn, {
                        icon: "mdi-delete",
                        variant: "text",
                        color: "error",
                        size: "small",
                        class: "ml-2",
                        onClick: ($event) => removeCustomExpression(index)
                      }, null, 8, ["onClick"])
                    ]);
                  }), 128)),
                  customExpressions.value.length === 0 ? (_openBlock$v(), _createElementBlock$c("div", _hoisted_2$f, " 无自定义表达式 ")) : _createCommentVNode$r("", true)
                ]),
                _: 1
              }),
              _createVNode$v(_component_v_card_actions, null, {
                default: _withCtx$v(() => [
                  _createVNode$v(_component_v_spacer),
                  _createVNode$v(_component_v_btn, {
                    color: "secondary",
                    onClick: _cache[1] || (_cache[1] = ($event) => _ctx.$emit("close"))
                  }, {
                    default: _withCtx$v(() => _cache[7] || (_cache[7] = [
                      _createTextVNode$v("取消")
                    ])),
                    _: 1
                  }),
                  _createVNode$v(_component_v_btn, {
                    color: "primary",
                    loading: loading.value,
                    onClick: updateDataVisibility
                  }, {
                    default: _withCtx$v(() => _cache[8] || (_cache[8] = [
                      _createTextVNode$v("保存")
                    ])),
                    _: 1
                  }, 8, ["loading"])
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _: 1
      });
    };
  }
});

const itemsPerPageOptions = [
  { title: "5", value: 5 },
  { title: "10", value: 10 },
  { title: "20", value: 20 },
  { title: "50", value: 50 },
  { title: "All", value: -1 }
];
const defaultMetadata = {
  source: "Manual",
  disabled: false,
  invisible_to: [],
  remark: "",
  time_modified: 0,
  patched: false
};
const defaultRule = {
  type: "DOMAIN-SUFFIX",
  payload: "",
  action: "DIRECT",
  priority: 0,
  meta: { ...defaultMetadata },
  rule_string: "DOMAIN-SUFFIX,,DIRECT"
};
const defaultProxy = {
  name: "",
  type: "ss",
  server: "",
  port: 443,
  udp: false,
  tfo: false,
  mptcp: false,
  tls: false,
  "skip-cert-verify": false,
  alpn: [],
  "ws-opts": {
    path: "/",
    headers: {},
    "v2ray-http-upgrade": false,
    "v2ray-http-upgrade-fast-open": false
  },
  "http-opts": { method: "GET", path: ["/"], headers: {} },
  "h2-opts": { host: [], path: "/" },
  "grpc-opts": { "grpc-service-name": "" },
  smux: {
    enabled: false,
    protocol: "h2mux",
    padding: false,
    statistic: false,
    "only-tcp": false,
    "brutal-opts": {
      enabled: false
    }
  },
  rescind: false
};
const defaultProxyGroup = {
  name: "",
  type: "select",
  url: "https://www.gstatic.com/generate_204",
  lazy: true,
  "disable-udp": false,
  "include-all": false,
  "include-all-proxies": false,
  "include-all-providers": false,
  "expected-status": "*",
  hidden: false,
  "max-failed-times": 5
};
const defaultHost = {
  domain: "",
  value: [],
  using_cloudflare: false,
  meta: { ...defaultMetadata }
};
const defaultRuleProvider = {
  type: "http",
  interval: 600,
  behavior: "classical",
  format: "yaml",
  "size-limit": 0,
  payload: []
};

const {defineComponent:_defineComponent$u} = await importShared('vue');

const {createTextVNode:_createTextVNode$u,resolveComponent:_resolveComponent$u,withCtx:_withCtx$u,createVNode:_createVNode$u,mergeProps:_mergeProps$m,unref:_unref$p,openBlock:_openBlock$u,createBlock:_createBlock$u,createCommentVNode:_createCommentVNode$q,toDisplayString:_toDisplayString$r} = await importShared('vue');
const _sfc_main$u = /* @__PURE__ */ _defineComponent$u({
  __name: "RuleActionMenu",
  props: {
    rule: {
      type: Object,
      required: true
    },
    hideVisibility: {
      type: Boolean,
      default: false
    }
  },
  emits: ["edit", "delete", "changeStatus", "editVisibility"],
  setup(__props, { emit: __emit }) {
    const emit = __emit;
    return (_ctx, _cache) => {
      const _component_v_icon = _resolveComponent$u("v-icon");
      const _component_v_btn = _resolveComponent$u("v-btn");
      const _component_v_tooltip = _resolveComponent$u("v-tooltip");
      const _component_v_list_item_title = _resolveComponent$u("v-list-item-title");
      const _component_v_list_item = _resolveComponent$u("v-list-item");
      const _component_v_list = _resolveComponent$u("v-list");
      const _component_v_menu = _resolveComponent$u("v-menu");
      return _openBlock$u(), _createBlock$u(_component_v_menu, { "min-width": "120" }, {
        activator: _withCtx$u(({ props }) => [
          _createVNode$u(_component_v_btn, _mergeProps$m({
            color: "secondary",
            icon: "",
            size: "small",
            variant: "text"
          }, props), {
            default: _withCtx$u(() => [
              _createVNode$u(_component_v_icon, null, {
                default: _withCtx$u(() => _cache[4] || (_cache[4] = [
                  _createTextVNode$u("mdi-dots-vertical")
                ])),
                _: 1
              })
            ]),
            _: 2
          }, 1040),
          _unref$p(isSystemRule)(__props.rule) ? (_openBlock$u(), _createBlock$u(_component_v_tooltip, {
            key: 0,
            activator: "parent",
            location: "top"
          }, {
            default: _withCtx$u(() => _cache[5] || (_cache[5] = [
              _createTextVNode$u(" 根据规则集自动添加 ")
            ])),
            _: 1
          })) : _createCommentVNode$q("", true)
        ]),
        default: _withCtx$u(() => [
          _createVNode$u(_component_v_list, { density: "compact" }, {
            default: _withCtx$u(() => [
              _createVNode$u(_component_v_list_item, {
                onClick: _cache[0] || (_cache[0] = ($event) => emit("changeStatus", !__props.rule.meta?.disabled))
              }, {
                prepend: _withCtx$u(() => [
                  _createVNode$u(_component_v_icon, {
                    size: "small",
                    color: __props.rule.meta?.disabled ? "success" : "grey"
                  }, {
                    default: _withCtx$u(() => [
                      _createTextVNode$u(_toDisplayString$r(__props.rule.meta?.disabled ? "mdi-play-circle-outline" : "mdi-stop-circle-outline"), 1)
                    ]),
                    _: 1
                  }, 8, ["color"])
                ]),
                default: _withCtx$u(() => [
                  _createVNode$u(_component_v_list_item_title, null, {
                    default: _withCtx$u(() => [
                      _createTextVNode$u(_toDisplayString$r(__props.rule.meta?.disabled ? "启用" : "禁用"), 1)
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              }),
              !_unref$p(isSystemRule)(__props.rule) ? (_openBlock$u(), _createBlock$u(_component_v_list_item, {
                key: 0,
                onClick: _cache[1] || (_cache[1] = ($event) => emit("edit"))
              }, {
                prepend: _withCtx$u(() => [
                  _createVNode$u(_component_v_icon, {
                    size: "small",
                    color: "primary"
                  }, {
                    default: _withCtx$u(() => _cache[6] || (_cache[6] = [
                      _createTextVNode$u("mdi-file-edit-outline")
                    ])),
                    _: 1
                  })
                ]),
                default: _withCtx$u(() => [
                  _createVNode$u(_component_v_list_item_title, null, {
                    default: _withCtx$u(() => _cache[7] || (_cache[7] = [
                      _createTextVNode$u("编辑")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              })) : _createCommentVNode$q("", true),
              !__props.hideVisibility ? (_openBlock$u(), _createBlock$u(_component_v_list_item, {
                key: 1,
                onClick: _cache[2] || (_cache[2] = ($event) => emit("editVisibility"))
              }, {
                prepend: _withCtx$u(() => [
                  _createVNode$u(_component_v_icon, {
                    size: "small",
                    color: "warning"
                  }, {
                    default: _withCtx$u(() => _cache[8] || (_cache[8] = [
                      _createTextVNode$u("mdi-eye-off-outline")
                    ])),
                    _: 1
                  })
                ]),
                default: _withCtx$u(() => [
                  _createVNode$u(_component_v_list_item_title, null, {
                    default: _withCtx$u(() => _cache[9] || (_cache[9] = [
                      _createTextVNode$u("隐藏")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              })) : _createCommentVNode$q("", true),
              !_unref$p(isSystemRule)(__props.rule) ? (_openBlock$u(), _createBlock$u(_component_v_list_item, {
                key: 2,
                onClick: _cache[3] || (_cache[3] = ($event) => emit("delete"))
              }, {
                prepend: _withCtx$u(() => [
                  _createVNode$u(_component_v_icon, {
                    size: "small",
                    color: "error"
                  }, {
                    default: _withCtx$u(() => _cache[10] || (_cache[10] = [
                      _createTextVNode$u("mdi-trash-can-outline")
                    ])),
                    _: 1
                  })
                ]),
                default: _withCtx$u(() => [
                  _createVNode$u(_component_v_list_item_title, null, {
                    default: _withCtx$u(() => _cache[11] || (_cache[11] = [
                      _createTextVNode$u("删除")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              })) : _createCommentVNode$q("", true)
            ]),
            _: 1
          })
        ]),
        _: 1
      });
    };
  }
});

const {defineComponent:_defineComponent$t} = await importShared('vue');

const {resolveComponent:_resolveComponent$t,createVNode:_createVNode$t,withCtx:_withCtx$t,Teleport:_Teleport$1,openBlock:_openBlock$t,createBlock:_createBlock$t,createCommentVNode:_createCommentVNode$p,unref:_unref$o,toDisplayString:_toDisplayString$q,createTextVNode:_createTextVNode$t,createElementVNode:_createElementVNode$n,Fragment:_Fragment$a,createElementBlock:_createElementBlock$b} = await importShared('vue');

const _hoisted_1$k = ["colspan"];
const {ref: ref$k} = await importShared('vue');
const ruleset$1 = "ruleset";
const _sfc_main$t = /* @__PURE__ */ _defineComponent$t({
  __name: "RulesetRulesTable",
  props: {
    sortedRules: {
      type: Array,
      required: true
    },
    page: {
      type: Number,
      required: true
    },
    itemsPerPage: {
      type: Number,
      required: true
    },
    rulesetPrefix: {
      type: String,
      required: true
    },
    searchRule: String,
    group: {
      type: Boolean,
      default: false
    }
  },
  emits: ["edit", "delete", "delete-batch", "reorder", "change-status", "change-status-batch", "editVisibility"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const headersRuleset = [
      { title: "", key: "handler", sortable: false, width: "1rem" },
      { title: "优先级", key: "priority", sortable: true, width: "3.5rem" },
      { title: "类型", key: "type", sortable: true },
      { title: "内容", key: "payload", sortable: true },
      { title: "出站", key: "action", sortable: true },
      { title: "规则集合", key: "name", value: "action", sortable: true },
      { title: "日期", key: "time_modified", sortable: true },
      { title: "", key: "status", sortable: false, width: "1rem" },
      { title: "", key: "actions", sortable: false, width: "1rem" }
    ];
    const groupHeaders = [
      { title: "优先级", key: "priority", sortable: true, width: "3.5rem" },
      { title: "类型", key: "type", sortable: true },
      { title: "内容", key: "payload", sortable: true },
      { title: "日期", key: "time_modified", sortable: true },
      { title: "", key: "status", sortable: false, width: "1rem" },
      { title: "", key: "actions", sortable: false, width: "1rem" }
    ];
    const groupBy = ref$k([
      {
        key: "action"
      }
    ]);
    const dragEnabled = ref$k(false);
    const dragItem = ref$k(null);
    const hoveredPriority = ref$k(-1);
    const selected = ref$k([]);
    function dragStart(event, priority) {
      const item = props.sortedRules.find((r) => r.priority === priority);
      if (!item) {
        event.preventDefault?.();
        return;
      }
      dragItem.value = item;
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
      }
    }
    function dragOver(event, priority) {
      event.preventDefault();
      if (event.dataTransfer) {
        event.dataTransfer.dropEffect = "move";
      }
      hoveredPriority.value = priority;
    }
    function drop(event, targetPriority) {
      if (dragItem.value && dragItem.value.priority !== targetPriority) {
        emit("reorder", targetPriority, dragItem.value.priority, ruleset$1);
      }
      dragItem.value = null;
      hoveredPriority.value = -1;
    }
    function dragEnd() {
      dragItem.value = null;
      hoveredPriority.value = -1;
    }
    function editRule(priority) {
      emit("edit", priority, ruleset$1);
    }
    function deleteRule(priority) {
      emit("delete", priority, ruleset$1);
    }
    function deleteSelected() {
      if (selected.value.length > 0) {
        emit("delete-batch", selected.value, ruleset$1);
        selected.value = [];
      }
    }
    function updateStatus(item, disabled) {
      emit("change-status", item.priority, disabled, ruleset$1);
    }
    function changeBatchStatus(disabled) {
      if (selected.value.length > 0) {
        emit("change-status-batch", selected.value, disabled, ruleset$1);
        selected.value = [];
      }
    }
    const rowProps = (data) => {
      const item = data.item;
      return {
        class: {
          "drop-over": item.priority === hoveredPriority.value,
          "dragging-item": dragItem.value?.priority === item.priority,
          "list-row": true,
          "text-grey": item.meta?.disabled
        },
        draggable: dragEnabled.value,
        onDragstart: (e) => dragStart(e, item.priority),
        onDragover: (e) => dragOver(e, item.priority),
        onDrop: (e) => drop(e, item.priority),
        onDragend: dragEnd
      };
    };
    return (_ctx, _cache) => {
      const _component_v_btn = _resolveComponent$t("v-btn");
      const _component_v_btn_group = _resolveComponent$t("v-btn-group");
      const _component_v_chip = _resolveComponent$t("v-chip");
      const _component_v_icon = _resolveComponent$t("v-icon");
      const _component_v_data_table = _resolveComponent$t("v-data-table");
      return _openBlock$t(), _createElementBlock$b(_Fragment$a, null, [
        selected.value.length > 0 ? (_openBlock$t(), _createBlock$t(_Teleport$1, {
          key: 0,
          to: "#ruleset-rules-table-batch-actions"
        }, [
          _createVNode$t(_component_v_btn_group, {
            rounded: "",
            variant: "tonal"
          }, {
            default: _withCtx$t(() => [
              _createVNode$t(_component_v_btn, {
                color: "success",
                "prepend-icon": "mdi-check",
                size: "small",
                onClick: _cache[0] || (_cache[0] = ($event) => changeBatchStatus(false))
              }),
              _createVNode$t(_component_v_btn, {
                color: "warning",
                "prepend-icon": "mdi-close",
                size: "small",
                onClick: _cache[1] || (_cache[1] = ($event) => changeBatchStatus(true))
              }),
              _createVNode$t(_component_v_btn, {
                color: "error",
                "prepend-icon": "mdi-trash-can-outline",
                size: "small",
                onClick: deleteSelected
              })
            ]),
            _: 1
          })
        ])) : _createCommentVNode$p("", true),
        __props.group ? (_openBlock$t(), _createBlock$t(_component_v_data_table, {
          key: 1,
          modelValue: selected.value,
          "onUpdate:modelValue": _cache[2] || (_cache[2] = ($event) => selected.value = $event),
          "fixed-header": "",
          class: "px-4",
          headers: groupHeaders,
          items: __props.sortedRules,
          "group-by": groupBy.value,
          search: __props.searchRule,
          page: __props.page,
          "items-per-page": __props.itemsPerPage,
          "items-per-page-options": _unref$o(itemsPerPageOptions),
          "item-key": "priority",
          "item-value": "priority",
          "show-select": "",
          density: "compact",
          "hide-default-footer": ""
        }, {
          "group-header": _withCtx$t(({ item, columns, toggleGroup, isGroupOpen }) => [
            _createElementVNode$n("tr", null, [
              _createElementVNode$n("td", {
                colspan: columns.length
              }, [
                _createVNode$t(_component_v_btn, {
                  icon: isGroupOpen(item) ? "mdi-chevron-down" : "mdi-chevron-right",
                  size: "small",
                  variant: "text",
                  onClick: ($event) => toggleGroup(item)
                }, null, 8, ["icon", "onClick"]),
                _createVNode$t(_component_v_chip, {
                  color: _unref$o(getActionColor)(item.value),
                  size: "small",
                  label: ""
                }, {
                  default: _withCtx$t(() => [
                    _createTextVNode$t(_toDisplayString$q(item.value), 1)
                  ]),
                  _: 2
                }, 1032, ["color"])
              ], 8, _hoisted_1$k)
            ])
          ]),
          "item.priority": _withCtx$t(({ item }) => [
            _createVNode$t(_component_v_chip, {
              size: "x-small",
              variant: "tonal",
              color: "secondary",
              class: "font-weight-bold"
            }, {
              default: _withCtx$t(() => [
                _createTextVNode$t(_toDisplayString$q(item.priority), 1)
              ]),
              _: 2
            }, 1024)
          ]),
          "item.type": _withCtx$t(({ item }) => [
            _createVNode$t(_component_v_chip, {
              color: _unref$o(getRuleTypeColor)(item.type),
              size: "small",
              label: "",
              variant: "tonal"
            }, {
              default: _withCtx$t(() => [
                _createTextVNode$t(_toDisplayString$q(item.type), 1)
              ]),
              _: 2
            }, 1032, ["color"])
          ]),
          "item.payload": _withCtx$t(({ value }) => [
            _createElementVNode$n("small", null, _toDisplayString$q(value), 1)
          ]),
          "item.time_modified": _withCtx$t(({ item }) => [
            _createElementVNode$n("small", null, _toDisplayString$q(item.meta?.time_modified ? _unref$o(timestampToDate)(item.meta.time_modified) : ""), 1)
          ]),
          "item.status": _withCtx$t(({ item }) => [
            _createVNode$t(_component_v_icon, {
              color: item.meta.disabled ? "grey" : "success"
            }, {
              default: _withCtx$t(() => [
                _createTextVNode$t(_toDisplayString$q(item.meta.disabled ? "mdi-close-circle-outline" : "mdi-check-circle-outline"), 1)
              ]),
              _: 2
            }, 1032, ["color"])
          ]),
          "item.actions": _withCtx$t(({ item }) => [
            _createVNode$t(_sfc_main$u, {
              rule: item,
              "hide-visibility": "",
              onEdit: ($event) => editRule(item.priority),
              onDelete: ($event) => deleteRule(item.priority),
              onChangeStatus: (disabled) => updateStatus(item, disabled)
            }, null, 8, ["rule", "onEdit", "onDelete", "onChangeStatus"])
          ]),
          _: 1
        }, 8, ["modelValue", "items", "group-by", "search", "page", "items-per-page", "items-per-page-options"])) : (_openBlock$t(), _createBlock$t(_component_v_data_table, {
          key: 2,
          modelValue: selected.value,
          "onUpdate:modelValue": _cache[5] || (_cache[5] = ($event) => selected.value = $event),
          "fixed-header": "",
          class: "px-4",
          headers: headersRuleset,
          items: __props.sortedRules,
          search: __props.searchRule,
          page: __props.page,
          "items-per-page": __props.itemsPerPage,
          "items-per-page-options": _unref$o(itemsPerPageOptions),
          "item-key": "priority",
          "item-value": "priority",
          "show-select": "",
          density: "compact",
          "hide-default-footer": "",
          "row-props": rowProps
        }, {
          "item.handler": _withCtx$t(({}) => [
            _createVNode$t(_component_v_icon, {
              class: "drag-handle mr-1",
              onMouseenter: _cache[3] || (_cache[3] = ($event) => dragEnabled.value = true),
              onMouseleave: _cache[4] || (_cache[4] = ($event) => dragEnabled.value = false)
            }, {
              default: _withCtx$t(() => _cache[6] || (_cache[6] = [
                _createTextVNode$t("mdi-drag-horizontal-variant ")
              ])),
              _: 1
            })
          ]),
          "item.priority": _withCtx$t(({ item }) => [
            _createVNode$t(_component_v_chip, {
              size: "x-small",
              variant: "tonal",
              color: "secondary",
              class: "font-weight-bold"
            }, {
              default: _withCtx$t(() => [
                _createTextVNode$t(_toDisplayString$q(item.priority), 1)
              ]),
              _: 2
            }, 1024)
          ]),
          "item.type": _withCtx$t(({ item }) => [
            _createVNode$t(_component_v_chip, {
              color: _unref$o(getRuleTypeColor)(item.type),
              size: "small",
              label: "",
              variant: "tonal"
            }, {
              default: _withCtx$t(() => [
                _createTextVNode$t(_toDisplayString$q(item.type), 1)
              ]),
              _: 2
            }, 1032, ["color"])
          ]),
          "item.payload": _withCtx$t(({ value }) => [
            _createElementVNode$n("small", null, _toDisplayString$q(value), 1)
          ]),
          "item.action": _withCtx$t(({ item }) => [
            _createVNode$t(_component_v_chip, {
              color: _unref$o(getActionColor)(item.action),
              size: "small",
              variant: "outlined",
              pill: ""
            }, {
              default: _withCtx$t(() => [
                _createTextVNode$t(_toDisplayString$q(item.action), 1)
              ]),
              _: 2
            }, 1032, ["color"])
          ]),
          "item.name": _withCtx$t(({ item }) => [
            _createElementVNode$n("small", null, _toDisplayString$q(__props.rulesetPrefix) + _toDisplayString$q(item.action), 1)
          ]),
          "item.time_modified": _withCtx$t(({ item }) => [
            _createElementVNode$n("small", null, _toDisplayString$q(item.meta?.time_modified ? _unref$o(timestampToDate)(item.meta.time_modified) : ""), 1)
          ]),
          "item.status": _withCtx$t(({ item }) => [
            _createVNode$t(_component_v_icon, {
              color: item.meta.disabled ? "grey" : "success"
            }, {
              default: _withCtx$t(() => [
                _createTextVNode$t(_toDisplayString$q(item.meta.disabled ? "mdi-close-circle-outline" : "mdi-check-circle-outline"), 1)
              ]),
              _: 2
            }, 1032, ["color"])
          ]),
          "item.actions": _withCtx$t(({ item }) => [
            _createVNode$t(_sfc_main$u, {
              rule: item,
              "hide-visibility": "",
              onEdit: ($event) => editRule(item.priority),
              onDelete: ($event) => deleteRule(item.priority),
              onChangeStatus: (disabled) => updateStatus(item, disabled)
            }, null, 8, ["rule", "onEdit", "onDelete", "onChangeStatus"])
          ]),
          _: 1
        }, 8, ["modelValue", "items", "search", "page", "items-per-page", "items-per-page-options"]))
      ], 64);
    };
  }
});

const {defineComponent:_defineComponent$s} = await importShared('vue');

const {toDisplayString:_toDisplayString$p,createTextVNode:_createTextVNode$s,resolveComponent:_resolveComponent$s,withCtx:_withCtx$s,createVNode:_createVNode$s,mergeProps:_mergeProps$l,openBlock:_openBlock$s,createBlock:_createBlock$s,createCommentVNode:_createCommentVNode$o,createElementVNode:_createElementVNode$m,unref:_unref$n} = await importShared('vue');

const _hoisted_1$j = { class: "d-flex justify-space-between align-center px-4 pt-3" };
const _hoisted_2$e = ["title"];
const _sfc_main$s = /* @__PURE__ */ _defineComponent$s({
  __name: "RuleCard",
  props: {
    rule: {
      type: Object,
      required: true
    },
    ruleset: {
      type: Object,
      required: true
    }
  },
  emits: ["edit", "delete", "change-status", "edit-visibility"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    function editRule(priority) {
      emit("edit", priority, props.ruleset);
    }
    function deleteRule(priority) {
      emit("delete", priority, props.ruleset);
    }
    function updateStatus(disabled) {
      emit("change-status", props.rule.priority, disabled, props.ruleset);
    }
    function editVisibility() {
      emit("edit-visibility", props.rule.priority, props.ruleset);
    }
    return (_ctx, _cache) => {
      const _component_v_chip = _resolveComponent$s("v-chip");
      const _component_v_icon = _resolveComponent$s("v-icon");
      const _component_v_tooltip = _resolveComponent$s("v-tooltip");
      const _component_v_col = _resolveComponent$s("v-col");
      const _component_v_row = _resolveComponent$s("v-row");
      const _component_v_card_text = _resolveComponent$s("v-card-text");
      const _component_v_divider = _resolveComponent$s("v-divider");
      const _component_v_spacer = _resolveComponent$s("v-spacer");
      const _component_v_card_actions = _resolveComponent$s("v-card-actions");
      const _component_v_card = _resolveComponent$s("v-card");
      return _openBlock$s(), _createBlock$s(_component_v_card, {
        rounded: "lg",
        elevation: "2",
        class: "rule-card h-100 transition-swing",
        variant: "tonal"
      }, {
        default: _withCtx$s(() => [
          _createElementVNode$m("div", _hoisted_1$j, [
            _createVNode$s(_component_v_chip, {
              variant: "flat",
              color: "secondary",
              class: "font-weight-bold mr-2",
              size: "small"
            }, {
              default: _withCtx$s(() => [
                _createTextVNode$s(_toDisplayString$p(__props.rule.priority), 1)
              ]),
              _: 1
            }),
            __props.rule.meta.invisible_to && __props.rule.meta.invisible_to.length > 0 ? (_openBlock$s(), _createBlock$s(_component_v_tooltip, {
              key: 0,
              text: "已配置可见性限制",
              location: "top"
            }, {
              activator: _withCtx$s(({ props: props2 }) => [
                _createVNode$s(_component_v_icon, _mergeProps$l(props2, {
                  size: "small",
                  color: "warning"
                }), {
                  default: _withCtx$s(() => _cache[2] || (_cache[2] = [
                    _createTextVNode$s(" mdi-eye-off-outline ")
                  ])),
                  _: 2
                }, 1040)
              ]),
              _: 1
            })) : _createCommentVNode$o("", true)
          ]),
          _createVNode$s(_component_v_card_text, { class: "pt-2 pb-4" }, {
            default: _withCtx$s(() => [
              _createVNode$s(_component_v_row, {
                "no-gutters": "",
                class: "mb-2 align-center"
              }, {
                default: _withCtx$s(() => [
                  _createVNode$s(_component_v_col, {
                    cols: "3",
                    class: "text-caption text-medium-emphasis"
                  }, {
                    default: _withCtx$s(() => _cache[3] || (_cache[3] = [
                      _createTextVNode$s("类型")
                    ])),
                    _: 1
                  }),
                  _createVNode$s(_component_v_col, { cols: "9" }, {
                    default: _withCtx$s(() => [
                      _createVNode$s(_component_v_chip, {
                        color: _unref$n(getRuleTypeColor)(__props.rule.type),
                        size: "x-small",
                        label: "",
                        variant: "tonal",
                        class: "font-weight-medium"
                      }, {
                        default: _withCtx$s(() => [
                          _createTextVNode$s(_toDisplayString$p(__props.rule.type), 1)
                        ]),
                        _: 1
                      }, 8, ["color"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              }),
              _createVNode$s(_component_v_row, {
                "no-gutters": "",
                class: "mb-2 align-center"
              }, {
                default: _withCtx$s(() => [
                  _createVNode$s(_component_v_col, {
                    cols: "3",
                    class: "text-caption text-medium-emphasis"
                  }, {
                    default: _withCtx$s(() => _cache[4] || (_cache[4] = [
                      _createTextVNode$s("内容")
                    ])),
                    _: 1
                  }),
                  _createVNode$s(_component_v_col, {
                    cols: "9",
                    class: "text-body-2 text-truncate font-weight-bold"
                  }, {
                    default: _withCtx$s(() => [
                      _createElementVNode$m("span", {
                        title: __props.rule.payload
                      }, _toDisplayString$p(__props.rule.payload), 9, _hoisted_2$e)
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              }),
              _createVNode$s(_component_v_row, {
                "no-gutters": "",
                class: "align-center"
              }, {
                default: _withCtx$s(() => [
                  _createVNode$s(_component_v_col, {
                    cols: "3",
                    class: "text-caption text-medium-emphasis"
                  }, {
                    default: _withCtx$s(() => _cache[5] || (_cache[5] = [
                      _createTextVNode$s("出站")
                    ])),
                    _: 1
                  }),
                  _createVNode$s(_component_v_col, { cols: "9" }, {
                    default: _withCtx$s(() => [
                      _createVNode$s(_component_v_chip, {
                        color: _unref$n(getActionColor)(__props.rule.action),
                        size: "x-small",
                        variant: "outlined",
                        class: "font-weight-medium"
                      }, {
                        default: _withCtx$s(() => [
                          _createTextVNode$s(_toDisplayString$p(__props.rule.action), 1)
                        ]),
                        _: 1
                      }, 8, ["color"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode$s(_component_v_divider),
          _createVNode$s(_component_v_card_actions, null, {
            default: _withCtx$s(() => [
              _createVNode$s(_component_v_icon, {
                color: __props.rule.meta.disabled ? "grey" : "success"
              }, {
                default: _withCtx$s(() => [
                  _createTextVNode$s(_toDisplayString$p(__props.rule.meta.disabled ? "mdi-close-circle-outline" : "mdi-check-circle-outline"), 1)
                ]),
                _: 1
              }, 8, ["color"]),
              _createVNode$s(_component_v_spacer),
              _createVNode$s(_sfc_main$u, {
                rule: __props.rule,
                "hide-visibility": __props.ruleset == "ruleset",
                onEdit: _cache[0] || (_cache[0] = ($event) => editRule(__props.rule.priority)),
                onDelete: _cache[1] || (_cache[1] = ($event) => deleteRule(__props.rule.priority)),
                onChangeStatus: updateStatus,
                onEditVisibility: editVisibility
              }, null, 8, ["rule", "hide-visibility"])
            ]),
            _: 1
          })
        ]),
        _: 1
      });
    };
  }
});

const RuleCard = /* @__PURE__ */ _export_sfc(_sfc_main$s, [["__scopeId", "data-v-5bf9d562"]]);

/**
 * lodash (Custom Build) <https://lodash.com/>
 * Build: `lodash modularize exports="npm" -o ./`
 * Copyright jQuery Foundation and other contributors <https://jquery.org/>
 * Released under MIT license <https://lodash.com/license>
 * Based on Underscore.js 1.8.3 <http://underscorejs.org/LICENSE>
 * Copyright Jeremy Ashkenas, DocumentCloud and Investigative Reporters & Editors
 */

/** Used as the `TypeError` message for "Functions" methods. */
var FUNC_ERROR_TEXT = 'Expected a function';

/** Used as references for various `Number` constants. */
var NAN = 0 / 0;

/** `Object#toString` result references. */
var symbolTag = '[object Symbol]';

/** Used to match leading and trailing whitespace. */
var reTrim = /^\s+|\s+$/g;

/** Used to detect bad signed hexadecimal string values. */
var reIsBadHex = /^[-+]0x[0-9a-f]+$/i;

/** Used to detect binary string values. */
var reIsBinary = /^0b[01]+$/i;

/** Used to detect octal string values. */
var reIsOctal = /^0o[0-7]+$/i;

/** Built-in method references without a dependency on `root`. */
var freeParseInt = parseInt;

/** Detect free variable `global` from Node.js. */
var freeGlobal = typeof commonjsGlobal == 'object' && commonjsGlobal && commonjsGlobal.Object === Object && commonjsGlobal;

/** Detect free variable `self`. */
var freeSelf = typeof self == 'object' && self && self.Object === Object && self;

/** Used as a reference to the global object. */
var root = freeGlobal || freeSelf || Function('return this')();

/** Used for built-in method references. */
var objectProto = Object.prototype;

/**
 * Used to resolve the
 * [`toStringTag`](http://ecma-international.org/ecma-262/7.0/#sec-object.prototype.tostring)
 * of values.
 */
var objectToString = objectProto.toString;

/* Built-in method references for those with the same name as other `lodash` methods. */
var nativeMax = Math.max,
    nativeMin = Math.min;

/**
 * Gets the timestamp of the number of milliseconds that have elapsed since
 * the Unix epoch (1 January 1970 00:00:00 UTC).
 *
 * @static
 * @memberOf _
 * @since 2.4.0
 * @category Date
 * @returns {number} Returns the timestamp.
 * @example
 *
 * _.defer(function(stamp) {
 *   console.log(_.now() - stamp);
 * }, _.now());
 * // => Logs the number of milliseconds it took for the deferred invocation.
 */
var now = function() {
  return root.Date.now();
};

/**
 * Creates a debounced function that delays invoking `func` until after `wait`
 * milliseconds have elapsed since the last time the debounced function was
 * invoked. The debounced function comes with a `cancel` method to cancel
 * delayed `func` invocations and a `flush` method to immediately invoke them.
 * Provide `options` to indicate whether `func` should be invoked on the
 * leading and/or trailing edge of the `wait` timeout. The `func` is invoked
 * with the last arguments provided to the debounced function. Subsequent
 * calls to the debounced function return the result of the last `func`
 * invocation.
 *
 * **Note:** If `leading` and `trailing` options are `true`, `func` is
 * invoked on the trailing edge of the timeout only if the debounced function
 * is invoked more than once during the `wait` timeout.
 *
 * If `wait` is `0` and `leading` is `false`, `func` invocation is deferred
 * until to the next tick, similar to `setTimeout` with a timeout of `0`.
 *
 * See [David Corbacho's article](https://css-tricks.com/debouncing-throttling-explained-examples/)
 * for details over the differences between `_.debounce` and `_.throttle`.
 *
 * @static
 * @memberOf _
 * @since 0.1.0
 * @category Function
 * @param {Function} func The function to debounce.
 * @param {number} [wait=0] The number of milliseconds to delay.
 * @param {Object} [options={}] The options object.
 * @param {boolean} [options.leading=false]
 *  Specify invoking on the leading edge of the timeout.
 * @param {number} [options.maxWait]
 *  The maximum time `func` is allowed to be delayed before it's invoked.
 * @param {boolean} [options.trailing=true]
 *  Specify invoking on the trailing edge of the timeout.
 * @returns {Function} Returns the new debounced function.
 * @example
 *
 * // Avoid costly calculations while the window size is in flux.
 * jQuery(window).on('resize', _.debounce(calculateLayout, 150));
 *
 * // Invoke `sendMail` when clicked, debouncing subsequent calls.
 * jQuery(element).on('click', _.debounce(sendMail, 300, {
 *   'leading': true,
 *   'trailing': false
 * }));
 *
 * // Ensure `batchLog` is invoked once after 1 second of debounced calls.
 * var debounced = _.debounce(batchLog, 250, { 'maxWait': 1000 });
 * var source = new EventSource('/stream');
 * jQuery(source).on('message', debounced);
 *
 * // Cancel the trailing debounced invocation.
 * jQuery(window).on('popstate', debounced.cancel);
 */
function debounce(func, wait, options) {
  var lastArgs,
      lastThis,
      maxWait,
      result,
      timerId,
      lastCallTime,
      lastInvokeTime = 0,
      leading = false,
      maxing = false,
      trailing = true;

  if (typeof func != 'function') {
    throw new TypeError(FUNC_ERROR_TEXT);
  }
  wait = toNumber(wait) || 0;
  if (isObject(options)) {
    leading = !!options.leading;
    maxing = 'maxWait' in options;
    maxWait = maxing ? nativeMax(toNumber(options.maxWait) || 0, wait) : maxWait;
    trailing = 'trailing' in options ? !!options.trailing : trailing;
  }

  function invokeFunc(time) {
    var args = lastArgs,
        thisArg = lastThis;

    lastArgs = lastThis = undefined;
    lastInvokeTime = time;
    result = func.apply(thisArg, args);
    return result;
  }

  function leadingEdge(time) {
    // Reset any `maxWait` timer.
    lastInvokeTime = time;
    // Start the timer for the trailing edge.
    timerId = setTimeout(timerExpired, wait);
    // Invoke the leading edge.
    return leading ? invokeFunc(time) : result;
  }

  function remainingWait(time) {
    var timeSinceLastCall = time - lastCallTime,
        timeSinceLastInvoke = time - lastInvokeTime,
        result = wait - timeSinceLastCall;

    return maxing ? nativeMin(result, maxWait - timeSinceLastInvoke) : result;
  }

  function shouldInvoke(time) {
    var timeSinceLastCall = time - lastCallTime,
        timeSinceLastInvoke = time - lastInvokeTime;

    // Either this is the first call, activity has stopped and we're at the
    // trailing edge, the system time has gone backwards and we're treating
    // it as the trailing edge, or we've hit the `maxWait` limit.
    return (lastCallTime === undefined || (timeSinceLastCall >= wait) ||
      (timeSinceLastCall < 0) || (maxing && timeSinceLastInvoke >= maxWait));
  }

  function timerExpired() {
    var time = now();
    if (shouldInvoke(time)) {
      return trailingEdge(time);
    }
    // Restart the timer.
    timerId = setTimeout(timerExpired, remainingWait(time));
  }

  function trailingEdge(time) {
    timerId = undefined;

    // Only invoke if we have `lastArgs` which means `func` has been
    // debounced at least once.
    if (trailing && lastArgs) {
      return invokeFunc(time);
    }
    lastArgs = lastThis = undefined;
    return result;
  }

  function cancel() {
    if (timerId !== undefined) {
      clearTimeout(timerId);
    }
    lastInvokeTime = 0;
    lastArgs = lastCallTime = lastThis = timerId = undefined;
  }

  function flush() {
    return timerId === undefined ? result : trailingEdge(now());
  }

  function debounced() {
    var time = now(),
        isInvoking = shouldInvoke(time);

    lastArgs = arguments;
    lastThis = this;
    lastCallTime = time;

    if (isInvoking) {
      if (timerId === undefined) {
        return leadingEdge(lastCallTime);
      }
      if (maxing) {
        // Handle invocations in a tight loop.
        timerId = setTimeout(timerExpired, wait);
        return invokeFunc(lastCallTime);
      }
    }
    if (timerId === undefined) {
      timerId = setTimeout(timerExpired, wait);
    }
    return result;
  }
  debounced.cancel = cancel;
  debounced.flush = flush;
  return debounced;
}

/**
 * Checks if `value` is the
 * [language type](http://www.ecma-international.org/ecma-262/7.0/#sec-ecmascript-language-types)
 * of `Object`. (e.g. arrays, functions, objects, regexes, `new Number(0)`, and `new String('')`)
 *
 * @static
 * @memberOf _
 * @since 0.1.0
 * @category Lang
 * @param {*} value The value to check.
 * @returns {boolean} Returns `true` if `value` is an object, else `false`.
 * @example
 *
 * _.isObject({});
 * // => true
 *
 * _.isObject([1, 2, 3]);
 * // => true
 *
 * _.isObject(_.noop);
 * // => true
 *
 * _.isObject(null);
 * // => false
 */
function isObject(value) {
  var type = typeof value;
  return !!value && (type == 'object' || type == 'function');
}

/**
 * Checks if `value` is object-like. A value is object-like if it's not `null`
 * and has a `typeof` result of "object".
 *
 * @static
 * @memberOf _
 * @since 4.0.0
 * @category Lang
 * @param {*} value The value to check.
 * @returns {boolean} Returns `true` if `value` is object-like, else `false`.
 * @example
 *
 * _.isObjectLike({});
 * // => true
 *
 * _.isObjectLike([1, 2, 3]);
 * // => true
 *
 * _.isObjectLike(_.noop);
 * // => false
 *
 * _.isObjectLike(null);
 * // => false
 */
function isObjectLike(value) {
  return !!value && typeof value == 'object';
}

/**
 * Checks if `value` is classified as a `Symbol` primitive or object.
 *
 * @static
 * @memberOf _
 * @since 4.0.0
 * @category Lang
 * @param {*} value The value to check.
 * @returns {boolean} Returns `true` if `value` is a symbol, else `false`.
 * @example
 *
 * _.isSymbol(Symbol.iterator);
 * // => true
 *
 * _.isSymbol('abc');
 * // => false
 */
function isSymbol(value) {
  return typeof value == 'symbol' ||
    (isObjectLike(value) && objectToString.call(value) == symbolTag);
}

/**
 * Converts `value` to a number.
 *
 * @static
 * @memberOf _
 * @since 4.0.0
 * @category Lang
 * @param {*} value The value to process.
 * @returns {number} Returns the number.
 * @example
 *
 * _.toNumber(3.2);
 * // => 3.2
 *
 * _.toNumber(Number.MIN_VALUE);
 * // => 5e-324
 *
 * _.toNumber(Infinity);
 * // => Infinity
 *
 * _.toNumber('3.2');
 * // => 3.2
 */
function toNumber(value) {
  if (typeof value == 'number') {
    return value;
  }
  if (isSymbol(value)) {
    return NAN;
  }
  if (isObject(value)) {
    var other = typeof value.valueOf == 'function' ? value.valueOf() : value;
    value = isObject(other) ? (other + '') : other;
  }
  if (typeof value != 'string') {
    return value === 0 ? value : +value;
  }
  value = value.replace(reTrim, '');
  var isBinary = reIsBinary.test(value);
  return (isBinary || reIsOctal.test(value))
    ? freeParseInt(value.slice(2), isBinary ? 2 : 8)
    : (reIsBadHex.test(value) ? NAN : +value);
}

var lodash_debounce = debounce;

const debounce$1 = /*@__PURE__*/getDefaultExportFromCjs(lodash_debounce);

const {defineComponent:_defineComponent$r} = await importShared('vue');

const {toDisplayString:_toDisplayString$o,createTextVNode:_createTextVNode$r,resolveComponent:_resolveComponent$r,withCtx:_withCtx$r,createVNode:_createVNode$r,openBlock:_openBlock$r,createBlock:_createBlock$r,createCommentVNode:_createCommentVNode$n,withModifiers:_withModifiers$4} = await importShared('vue');

const {ref: ref$j,computed: computed$8,toRaw: toRaw$8} = await importShared('vue');
const _sfc_main$r = /* @__PURE__ */ _defineComponent$r({
  __name: "RuleDialog",
  props: {
    // 父组件传递的规则数据
    initialRule: {
      type: Object,
      required: true
    },
    isAdding: {
      type: Boolean,
      default: true
    },
    editingType: {
      type: String,
      default: "top"
    },
    ruleProviderNames: {
      type: Array,
      default: () => []
    },
    geoRules: {
      type: Object,
      default: () => ({ geoip: [], geosite: [] })
    },
    customOutbounds: {
      type: Array,
      default: () => []
    },
    api: {
      type: Object,
      required: true
    }
  },
  emits: ["close", "refresh", "show-snackbar", "show-error"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const rule = ref$j(structuredClone(toRaw$8(props.initialRule)));
    const loading = ref$j(false);
    const ruleForm = ref$j(null);
    const geoSearch = ref$j("");
    const geoIPSearch = ref$j("");
    const geoFilterLoading = ref$j(false);
    const filteredGeoItems = ref$j([]);
    const ruleTypes = computed$8(() => {
      const allTypes = [
        "DOMAIN",
        "DOMAIN-SUFFIX",
        "DOMAIN-KEYWORD",
        "DOMAIN-REGEX",
        "DOMAIN-WILDCARD",
        "GEOSITE",
        "GEOIP",
        "IP-CIDR",
        "IP-CIDR6",
        "IP-SUFFIX",
        "IP-ASN",
        "SRC-GEOIP",
        "SRC-IP-ASN",
        "SRC-IP-CIDR",
        "SRC-IP-SUFFIX",
        "DST-PORT",
        "SRC-PORT",
        "IN-PORT",
        "IN-TYPE",
        "IN-USER",
        "IN-NAME",
        "PROCESS-PATH",
        "PROCESS-PATH-REGEX",
        "PROCESS-NAME",
        "PROCESS-NAME-REGEX",
        "UID",
        "NETWORK",
        "DSCP",
        "RULE-SET",
        "AND",
        "OR",
        "NOT",
        "SUB-RULE",
        "MATCH"
      ];
      if (props.editingType === "ruleset") {
        return allTypes.filter((type) => !["SUB-RULE", "RULE-SET"].includes(type));
      }
      return allTypes;
    });
    const showAdditionalParams = computed$8(() => {
      return ["IP-CIDR", "IP-CIDR6", "IP-ASN", "GEOIP"].includes(rule.value.type);
    });
    const onGeoSearch = (val) => {
      geoSearch.value = val;
      performGeoSiteFilter(val);
    };
    const onGeoIPSearch = (val) => {
      geoIPSearch.value = val;
      performGeoIPFilter(val);
    };
    const performGeoSiteFilter = debounce$1((val) => {
      if (!val) {
        filteredGeoItems.value = [];
        geoFilterLoading.value = false;
        return;
      }
      geoFilterLoading.value = true;
      filteredGeoItems.value = props.geoRules.geosite.filter(
        (item) => item.toLowerCase().includes(val.toLowerCase())
      );
      geoFilterLoading.value = false;
    }, 100);
    const performGeoIPFilter = debounce$1((val) => {
      if (!val) {
        filteredGeoItems.value = [];
        geoFilterLoading.value = false;
        return;
      }
      geoFilterLoading.value = true;
      filteredGeoItems.value = props.geoRules.geoip.filter(
        (item) => item.toLowerCase().includes(val.toLowerCase())
      );
      geoFilterLoading.value = false;
    }, 200);
    const onGeoSiteBlur = () => {
      if (!filteredGeoItems.value.includes(geoSearch.value)) {
        rule.value.payload = geoSearch.value;
      }
    };
    const onGeoIPBlur = () => {
      if (!filteredGeoItems.value.includes(geoIPSearch.value)) {
        rule.value.payload = geoIPSearch.value;
      }
    };
    const actions = computed$8(() => [
      "DIRECT",
      "REJECT",
      "REJECT-DROP",
      "PASS",
      "COMPATIBLE",
      ...props.customOutbounds.map((outbound) => outbound)
    ]);
    const additionalParamOptions = ref$j([
      { title: "无", value: "" },
      { title: "no-resolve", value: "no-resolve" },
      { title: "src", value: "src" }
    ]);
    const payloadRules = computed$8(() => {
      return [
        (v) => {
          if (rule.value.type === "MATCH") {
            return true;
          }
          return !!v || "内容不能为空";
        }
      ];
    });
    async function saveRule() {
      const { valid } = await ruleForm.value.validate();
      if (!valid) return;
      loading.value = true;
      try {
        if (rule.value?.payload) {
          rule.value.payload = rule.value.payload.trim();
        }
        const requestData = { ...rule.value };
        const priority = props.isAdding ? "" : `/${props.initialRule.priority}`;
        const method = props.isAdding ? "post" : "patch";
        const result = await props.api[method](
          `/plugin/ClashRuleProvider/rules/${props.editingType}${priority}`,
          requestData
        );
        if (!result.success) {
          emit("show-error", "保存规则失败: " + (result.message || "未知错误"));
          emit("show-snackbar", {
            show: true,
            message: "保存规则合失败",
            color: "error"
          });
          return;
        }
        emit("close");
        emit("refresh", ["top", "ruleset"]);
        emit("show-snackbar", {
          show: true,
          message: props.isAdding ? "规则添加成功" : "规则更新成功",
          color: "success"
        });
      } catch (err) {
        if (err instanceof Error) emit("show-error", "保存规则失败: " + (err.message || "未知错误"));
        emit("show-snackbar", {
          show: true,
          message: "保存规则失败",
          color: "error"
        });
      } finally {
        loading.value = false;
      }
    }
    return (_ctx, _cache) => {
      const _component_v_card_title = _resolveComponent$r("v-card-title");
      const _component_v_select = _resolveComponent$r("v-select");
      const _component_v_autocomplete = _resolveComponent$r("v-autocomplete");
      const _component_v_combobox = _resolveComponent$r("v-combobox");
      const _component_v_text_field = _resolveComponent$r("v-text-field");
      const _component_v_card_text = _resolveComponent$r("v-card-text");
      const _component_v_spacer = _resolveComponent$r("v-spacer");
      const _component_v_btn = _resolveComponent$r("v-btn");
      const _component_v_card_actions = _resolveComponent$r("v-card-actions");
      const _component_v_card = _resolveComponent$r("v-card");
      const _component_v_form = _resolveComponent$r("v-form");
      const _component_v_dialog = _resolveComponent$r("v-dialog");
      return _openBlock$r(), _createBlock$r(_component_v_dialog, { "max-width": "40rem" }, {
        default: _withCtx$r(() => [
          _createVNode$r(_component_v_form, {
            ref_key: "ruleForm",
            ref: ruleForm,
            onSubmit: _withModifiers$4(saveRule, ["prevent"])
          }, {
            default: _withCtx$r(() => [
              _createVNode$r(_component_v_card, null, {
                default: _withCtx$r(() => [
                  _createVNode$r(_component_v_card_title, null, {
                    default: _withCtx$r(() => [
                      _createTextVNode$r(_toDisplayString$o(__props.isAdding ? "添加规则" : "编辑规则"), 1)
                    ]),
                    _: 1
                  }),
                  _createVNode$r(_component_v_card_text, null, {
                    default: _withCtx$r(() => [
                      _createVNode$r(_component_v_select, {
                        modelValue: rule.value.type,
                        "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => rule.value.type = $event),
                        items: ruleTypes.value,
                        label: "规则类型",
                        required: "",
                        class: "mb-4"
                      }, null, 8, ["modelValue", "items"]),
                      rule.value.type === "RULE-SET" ? (_openBlock$r(), _createBlock$r(_component_v_select, {
                        key: 0,
                        modelValue: rule.value.payload,
                        "onUpdate:modelValue": _cache[1] || (_cache[1] = ($event) => rule.value.payload = $event),
                        items: props.ruleProviderNames,
                        label: "选择规则集",
                        required: "",
                        rules: [(v) => !!v || "请选择一个有效的规则集"],
                        class: "mb-4"
                      }, null, 8, ["modelValue", "items", "rules"])) : rule.value.type === "GEOSITE" ? (_openBlock$r(), _createBlock$r(_component_v_autocomplete, {
                        key: 1,
                        modelValue: rule.value.payload,
                        "onUpdate:modelValue": _cache[2] || (_cache[2] = ($event) => rule.value.payload = $event),
                        search: geoSearch.value,
                        items: filteredGeoItems.value,
                        loading: geoFilterLoading.value,
                        "hide-no-data": "",
                        "hide-selected": "",
                        label: "内容",
                        "no-filter": "",
                        solo: "",
                        "custom-filter": () => true,
                        clearable: "",
                        class: "mb-4",
                        rules: payloadRules.value,
                        "onUpdate:search": onGeoSearch,
                        onBlur: onGeoSiteBlur
                      }, null, 8, ["modelValue", "search", "items", "loading", "rules"])) : rule.value.type === "GEOIP" ? (_openBlock$r(), _createBlock$r(_component_v_autocomplete, {
                        key: 2,
                        modelValue: rule.value.payload,
                        "onUpdate:modelValue": _cache[3] || (_cache[3] = ($event) => rule.value.payload = $event),
                        search: geoIPSearch.value,
                        items: filteredGeoItems.value,
                        loading: geoFilterLoading.value,
                        "hide-no-data": "",
                        "hide-selected": "",
                        label: "内容",
                        "no-filter": "",
                        solo: "",
                        "custom-filter": () => true,
                        clearable: "",
                        class: "mb-4",
                        rules: payloadRules.value,
                        "onUpdate:search": onGeoIPSearch,
                        onBlur: onGeoIPBlur
                      }, null, 8, ["modelValue", "search", "items", "loading", "rules"])) : rule.value.type === "AND" || rule.value.type === "OR" || rule.value.type === "NOT" ? (_openBlock$r(), _createBlock$r(_component_v_combobox, {
                        key: 3,
                        modelValue: rule.value.conditions,
                        "onUpdate:modelValue": _cache[4] || (_cache[4] = ($event) => rule.value.conditions = $event),
                        label: "条件",
                        multiple: "",
                        chips: "",
                        hint: "「(DOMAIN,baidu.com)」,「(NETWORK,TCP)」",
                        clearable: "",
                        required: "",
                        class: "mb-4"
                      }, null, 8, ["modelValue"])) : rule.value.type === "SUB-RULE" ? (_openBlock$r(), _createBlock$r(_component_v_text_field, {
                        key: 4,
                        modelValue: rule.value.condition,
                        "onUpdate:modelValue": _cache[5] || (_cache[5] = ($event) => rule.value.condition = $event),
                        label: "条件",
                        required: "",
                        placeholder: "(AND,(DOMAIN,baidu.com),(NETWORK,TCP))",
                        rules: payloadRules.value,
                        class: "mb-4"
                      }, null, 8, ["modelValue", "rules"])) : (_openBlock$r(), _createBlock$r(_component_v_text_field, {
                        key: 5,
                        modelValue: rule.value.payload,
                        "onUpdate:modelValue": _cache[6] || (_cache[6] = ($event) => rule.value.payload = $event),
                        label: "内容",
                        required: "",
                        rules: payloadRules.value,
                        class: "mb-4"
                      }, null, 8, ["modelValue", "rules"])),
                      rule.value.type === "SUB-RULE" ? (_openBlock$r(), _createBlock$r(_component_v_text_field, {
                        key: 6,
                        modelValue: rule.value.action,
                        "onUpdate:modelValue": _cache[7] || (_cache[7] = ($event) => rule.value.action = $event),
                        label: "子规则",
                        required: "",
                        class: "mb-4"
                      }, null, 8, ["modelValue"])) : (_openBlock$r(), _createBlock$r(_component_v_select, {
                        key: 7,
                        modelValue: rule.value.action,
                        "onUpdate:modelValue": _cache[8] || (_cache[8] = ($event) => rule.value.action = $event),
                        items: actions.value,
                        label: "出站",
                        required: "",
                        class: "mb-4"
                      }, null, 8, ["modelValue", "items"])),
                      showAdditionalParams.value ? (_openBlock$r(), _createBlock$r(_component_v_select, {
                        key: 8,
                        modelValue: rule.value.additional_params,
                        "onUpdate:modelValue": _cache[9] || (_cache[9] = ($event) => rule.value.additional_params = $event),
                        label: "附加参数",
                        items: additionalParamOptions.value,
                        clearable: "",
                        hint: "可选参数",
                        "persistent-hint": "",
                        class: "mb-4"
                      }, null, 8, ["modelValue", "items"])) : _createCommentVNode$n("", true),
                      _createVNode$r(_component_v_text_field, {
                        modelValue: rule.value.priority,
                        "onUpdate:modelValue": _cache[10] || (_cache[10] = ($event) => rule.value.priority = $event),
                        modelModifiers: { number: true },
                        type: "number",
                        label: "优先级",
                        hint: "数字越小优先级越高",
                        "persistent-hint": ""
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  }),
                  _createVNode$r(_component_v_card_actions, null, {
                    default: _withCtx$r(() => [
                      _createVNode$r(_component_v_spacer),
                      _createVNode$r(_component_v_btn, {
                        color: "secondary",
                        onClick: _cache[11] || (_cache[11] = ($event) => emit("close"))
                      }, {
                        default: _withCtx$r(() => _cache[12] || (_cache[12] = [
                          _createTextVNode$r("取消")
                        ])),
                        _: 1
                      }),
                      _createVNode$r(_component_v_btn, {
                        color: "primary",
                        type: "submit",
                        loading: loading.value
                      }, {
                        default: _withCtx$r(() => _cache[13] || (_cache[13] = [
                          _createTextVNode$r("保存 ")
                        ])),
                        _: 1
                      }, 8, ["loading"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          }, 512)
        ]),
        _: 1
      });
    };
  }
});

const {defineComponent:_defineComponent$q} = await importShared('vue');

const {resolveComponent:_resolveComponent$q,createVNode:_createVNode$q,withCtx:_withCtx$q,createElementVNode:_createElementVNode$l,renderList:_renderList$9,Fragment:_Fragment$9,openBlock:_openBlock$q,createElementBlock:_createElementBlock$a,createBlock:_createBlock$q,unref:_unref$m,toDisplayString:_toDisplayString$n,createTextVNode:_createTextVNode$q,mergeProps:_mergeProps$k,createCommentVNode:_createCommentVNode$m} = await importShared('vue');

const _hoisted_1$i = { class: "mb-2 position-relative" };
const _hoisted_2$d = { class: "pa-4" };
const _hoisted_3$d = { class: "d-none d-sm-flex clash-data-table" };
const _hoisted_4$b = { class: "d-sm-none" };
const _hoisted_5$8 = {
  class: "pa-4",
  style: { "min-height": "4rem" }
};
const {computed: computed$7,ref: ref$i,toRaw: toRaw$7} = await importShared('vue');
const _sfc_main$q = /* @__PURE__ */ _defineComponent$q({
  __name: "RulesetRulesTab",
  props: {
    rules: {},
    rulesetPrefix: {},
    api: {},
    ruleProviderNames: {},
    geoRules: {},
    customOutbounds: {}
  },
  emits: ["refresh", "show-snackbar", "show-error"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const searchRulesetRule = ref$i("");
    const pageRuleset = ref$i(1);
    const itemsPerPageRuleset = ref$i(10);
    const loading = ref$i(false);
    const group = ref$i(false);
    const ruleDialogVisible = ref$i(false);
    const editingPriority = ref$i(null);
    const currentRule = ref$i({ ...defaultRule });
    const editingType = ref$i("ruleset");
    const filteredRulesetRules = computed$7(() => {
      if (!searchRulesetRule.value) return props.rules;
      const keyword = searchRulesetRule.value.toLowerCase();
      return props.rules.filter(
        (item) => Object.values(item).some((val) => String(val).toLowerCase().includes(keyword))
      );
    });
    const pageCountRuleset = computed$7(() => {
      if (itemsPerPageRuleset.value === -1) {
        return 1;
      }
      return Math.ceil(filteredRulesetRules.value.length / itemsPerPageRuleset.value);
    });
    const paginatedRulesetRules = computed$7(() => {
      const start = (pageRuleset.value - 1) * itemsPerPageRuleset.value;
      const end = start + itemsPerPageRuleset.value;
      return filteredRulesetRules.value.slice(start, end);
    });
    function openAddRuleDialog() {
      editingPriority.value = null;
      const nextPriority = props.rules.length > 0 ? props.rules[props.rules.length - 1].priority + 1 : 0;
      currentRule.value = { ...defaultRule };
      currentRule.value.priority = nextPriority;
      ruleDialogVisible.value = true;
    }
    function editRule(priority) {
      const rule = props.rules.find((r) => r.priority === priority);
      if (rule) {
        editingPriority.value = priority;
        currentRule.value = structuredClone(toRaw$7(rule));
        ruleDialogVisible.value = true;
      }
    }
    async function deleteRule(priority) {
      loading.value = true;
      try {
        await props.api.delete(`/plugin/ClashRuleProvider/rules/ruleset/${priority}`);
        emit("refresh", ["top", "ruleset"]);
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", err.message || "删除规则失败");
        }
      } finally {
        loading.value = false;
      }
    }
    async function deleteRules(priorities) {
      loading.value = true;
      try {
        await props.api.delete("/plugin/ClashRuleProvider/rules/ruleset", {
          data: { rules_priority: priorities }
        });
        emit("refresh", ["top", "ruleset"]);
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", err.message || "批量删除规则失败");
        }
      } finally {
        loading.value = false;
      }
    }
    async function handleReorderRule(targetPriority, movedPriority) {
      loading.value = true;
      try {
        await props.api.put(`/plugin/ClashRuleProvider/reorder-rules/ruleset/${targetPriority}`, {
          moved_priority: movedPriority
        });
        emit("refresh", ["top", "ruleset"]);
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", err.message || "重排序失败");
        }
      } finally {
        loading.value = false;
      }
    }
    async function handleStatusChange(priority, disabled) {
      loading.value = true;
      try {
        await props.api.post(`/plugin/ClashRuleProvider/rules/ruleset/metadata/disabled`, {
          [priority]: disabled
        });
        emit("refresh", ["top", "ruleset"]);
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", err.message || "更新规则状态失败");
        }
      } finally {
        loading.value = false;
      }
    }
    async function handleBatchStatusChange(priorities, disabled) {
      loading.value = true;
      try {
        const payload = priorities.reduce((acc, p) => ({ ...acc, [p]: disabled }), {});
        await props.api.post(`/plugin/ClashRuleProvider/rules/ruleset/metadata/disabled`, payload);
        emit("refresh", ["top", "ruleset"]);
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", err.message || "批量更新规则状态失败");
        }
      } finally {
        loading.value = false;
      }
    }
    function closeRuleDialog() {
      ruleDialogVisible.value = false;
    }
    return (_ctx, _cache) => {
      const _component_v_progress_circular = _resolveComponent$q("v-progress-circular");
      const _component_v_overlay = _resolveComponent$q("v-overlay");
      const _component_v_text_field = _resolveComponent$q("v-text-field");
      const _component_v_col = _resolveComponent$q("v-col");
      const _component_v_btn = _resolveComponent$q("v-btn");
      const _component_v_btn_group = _resolveComponent$q("v-btn-group");
      const _component_v_row = _resolveComponent$q("v-row");
      const _component_v_pagination = _resolveComponent$q("v-pagination");
      const _component_v_list_item_title = _resolveComponent$q("v-list-item-title");
      const _component_v_list_item = _resolveComponent$q("v-list-item");
      const _component_v_list = _resolveComponent$q("v-list");
      const _component_v_menu = _resolveComponent$q("v-menu");
      const _component_v_divider = _resolveComponent$q("v-divider");
      return _openBlock$q(), _createElementBlock$a("div", _hoisted_1$i, [
        _createVNode$q(_component_v_overlay, {
          modelValue: loading.value,
          "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => loading.value = $event),
          contained: "",
          class: "align-center justify-center"
        }, {
          default: _withCtx$q(() => [
            _createVNode$q(_component_v_progress_circular, {
              indeterminate: "",
              color: "primary"
            })
          ]),
          _: 1
        }, 8, ["modelValue"]),
        _createElementVNode$l("div", _hoisted_2$d, [
          _createVNode$q(_component_v_row, {
            align: "center",
            "no-gutters": ""
          }, {
            default: _withCtx$q(() => [
              _createVNode$q(_component_v_col, {
                cols: "10",
                sm: "6",
                class: "d-flex justify-start"
              }, {
                default: _withCtx$q(() => [
                  _createVNode$q(_component_v_text_field, {
                    modelValue: searchRulesetRule.value,
                    "onUpdate:modelValue": _cache[1] || (_cache[1] = ($event) => searchRulesetRule.value = $event),
                    label: "搜索规则",
                    clearable: "",
                    density: "compact",
                    variant: "solo-filled",
                    "hide-details": "",
                    class: "search-field",
                    "prepend-inner-icon": "mdi-magnify",
                    flat: "",
                    rounded: "pill",
                    "single-line": "",
                    disabled: loading.value
                  }, null, 8, ["modelValue", "disabled"])
                ]),
                _: 1
              }),
              _createVNode$q(_component_v_col, {
                cols: "2",
                sm: "6",
                class: "d-flex justify-end"
              }, {
                default: _withCtx$q(() => [
                  _createVNode$q(_component_v_btn_group, {
                    variant: "outlined",
                    rounded: "",
                    divided: ""
                  }, {
                    default: _withCtx$q(() => [
                      _createVNode$q(_component_v_btn, {
                        class: "d-none d-sm-flex",
                        icon: group.value ? "mdi-format-list-bulleted" : "mdi-format-list-group",
                        disabled: loading.value,
                        onClick: _cache[2] || (_cache[2] = ($event) => group.value = !group.value)
                      }, null, 8, ["icon", "disabled"]),
                      _createVNode$q(_component_v_btn, {
                        icon: "mdi-plus",
                        disabled: loading.value,
                        onClick: openAddRuleDialog
                      }, null, 8, ["disabled"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _createElementVNode$l("div", _hoisted_3$d, [
          _createVNode$q(_sfc_main$t, {
            group: group.value,
            "sorted-rules": _ctx.rules,
            page: pageRuleset.value,
            "items-per-page": itemsPerPageRuleset.value,
            "ruleset-prefix": _ctx.rulesetPrefix,
            "search-rule": searchRulesetRule.value,
            onEdit: editRule,
            onDelete: deleteRule,
            onDeleteBatch: deleteRules,
            onReorder: handleReorderRule,
            onChangeStatus: handleStatusChange,
            onChangeStatusBatch: handleBatchStatusChange
          }, null, 8, ["group", "sorted-rules", "page", "items-per-page", "ruleset-prefix", "search-rule"])
        ]),
        _createElementVNode$l("div", _hoisted_4$b, [
          _createVNode$q(_component_v_row, null, {
            default: _withCtx$q(() => [
              (_openBlock$q(true), _createElementBlock$a(_Fragment$9, null, _renderList$9(paginatedRulesetRules.value, (item) => {
                return _openBlock$q(), _createBlock$q(_component_v_col, {
                  key: item.priority,
                  cols: "12"
                }, {
                  default: _withCtx$q(() => [
                    _createVNode$q(RuleCard, {
                      ruleset: "ruleset",
                      rule: item,
                      onDelete: deleteRule,
                      onEdit: editRule,
                      onChangeStatus: handleStatusChange
                    }, null, 8, ["rule"])
                  ]),
                  _: 2
                }, 1024);
              }), 128))
            ]),
            _: 1
          })
        ]),
        _createElementVNode$l("div", _hoisted_5$8, [
          _createVNode$q(_component_v_row, {
            align: "center",
            "no-gutters": ""
          }, {
            default: _withCtx$q(() => [
              _createVNode$q(_component_v_col, {
                cols: "2",
                md: "2"
              }, {
                default: _withCtx$q(() => _cache[9] || (_cache[9] = [
                  _createElementVNode$l("div", { id: "ruleset-rules-table-batch-actions" }, null, -1)
                ])),
                _: 1
              }),
              _createVNode$q(_component_v_col, {
                cols: "8",
                md: "8",
                class: "d-flex justify-center"
              }, {
                default: _withCtx$q(() => [
                  _createVNode$q(_component_v_pagination, {
                    modelValue: pageRuleset.value,
                    "onUpdate:modelValue": _cache[3] || (_cache[3] = ($event) => pageRuleset.value = $event),
                    length: pageCountRuleset.value,
                    "total-visible": "5",
                    rounded: "circle",
                    class: "d-none d-sm-flex my-0",
                    disabled: loading.value
                  }, null, 8, ["modelValue", "length", "disabled"]),
                  _createVNode$q(_component_v_pagination, {
                    modelValue: pageRuleset.value,
                    "onUpdate:modelValue": _cache[4] || (_cache[4] = ($event) => pageRuleset.value = $event),
                    length: pageCountRuleset.value,
                    "total-visible": "0",
                    rounded: "circle",
                    class: "d-sm-none my-0",
                    disabled: loading.value
                  }, null, 8, ["modelValue", "length", "disabled"])
                ]),
                _: 1
              }),
              _createVNode$q(_component_v_col, {
                cols: "2",
                md: "2",
                class: "d-flex justify-end"
              }, {
                default: _withCtx$q(() => [
                  _createVNode$q(_component_v_menu, null, {
                    activator: _withCtx$q(({ props: props2 }) => [
                      _createVNode$q(_component_v_btn, _mergeProps$k(props2, {
                        icon: "",
                        rounded: "circle",
                        variant: "tonal",
                        disabled: loading.value
                      }), {
                        default: _withCtx$q(() => [
                          _createTextVNode$q(_toDisplayString$n(_unref$m(pageTitle)(itemsPerPageRuleset.value)), 1)
                        ]),
                        _: 2
                      }, 1040, ["disabled"])
                    ]),
                    default: _withCtx$q(() => [
                      _createVNode$q(_component_v_list, null, {
                        default: _withCtx$q(() => [
                          (_openBlock$q(true), _createElementBlock$a(_Fragment$9, null, _renderList$9(_unref$m(itemsPerPageOptions), (item, index) => {
                            return _openBlock$q(), _createBlock$q(_component_v_list_item, {
                              key: index,
                              value: item.value,
                              onClick: ($event) => itemsPerPageRuleset.value = item.value
                            }, {
                              default: _withCtx$q(() => [
                                _createVNode$q(_component_v_list_item_title, null, {
                                  default: _withCtx$q(() => [
                                    _createTextVNode$q(_toDisplayString$n(item.title), 1)
                                  ]),
                                  _: 2
                                }, 1024)
                              ]),
                              _: 2
                            }, 1032, ["value", "onClick"]);
                          }), 128))
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _createVNode$q(_component_v_divider),
        _cache[10] || (_cache[10] = _createElementVNode$l("div", { class: "text-caption text-grey mt-2" }, "* 对规则集的修改会在 Clash 中立即生效。", -1)),
        ruleDialogVisible.value ? (_openBlock$q(), _createBlock$q(_sfc_main$r, {
          key: 0,
          modelValue: ruleDialogVisible.value,
          "onUpdate:modelValue": _cache[5] || (_cache[5] = ($event) => ruleDialogVisible.value = $event),
          "initial-rule": currentRule.value,
          "is-adding": editingPriority.value === null,
          "editing-type": editingType.value,
          "rule-provider-names": _ctx.ruleProviderNames,
          "geo-rules": _ctx.geoRules,
          "custom-outbounds": _ctx.customOutbounds,
          api: _ctx.api,
          onRefresh: _cache[6] || (_cache[6] = (v) => emit("refresh", v)),
          onShowSnackbar: _cache[7] || (_cache[7] = (val) => emit("show-snackbar", val)),
          onShowError: _cache[8] || (_cache[8] = (msg) => emit("show-error", msg)),
          onClose: closeRuleDialog
        }, null, 8, ["modelValue", "initial-rule", "is-adding", "editing-type", "rule-provider-names", "geo-rules", "custom-outbounds", "api"])) : _createCommentVNode$m("", true)
      ]);
    };
  }
});

const {defineComponent:_defineComponent$p} = await importShared('vue');

const {unref:_unref$l,resolveComponent:_resolveComponent$p,createVNode:_createVNode$p,withCtx:_withCtx$p,Teleport:_Teleport,openBlock:_openBlock$p,createBlock:_createBlock$p,createCommentVNode:_createCommentVNode$l,createTextVNode:_createTextVNode$p,toDisplayString:_toDisplayString$m,createElementVNode:_createElementVNode$k,mergeProps:_mergeProps$j} = await importShared('vue');

const _hoisted_1$h = { class: "d-flex align-center" };
const {ref: ref$h} = await importShared('vue');
const ruleset = "top";
const _sfc_main$p = /* @__PURE__ */ _defineComponent$p({
  __name: "TopRulesTable",
  props: {
    sortedRules: {
      type: Array,
      required: true
    },
    page: {
      type: Number,
      required: true
    },
    itemsPerPage: {
      type: Number,
      required: true
    },
    searchRule: String
  },
  emits: ["edit", "delete", "delete-batch", "reorder", "change-status", "change-status-batch", "editVisibility"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const headers = ref$h([
      { title: "", key: "handler", sortable: false, width: "1rem" },
      { title: "优先级", key: "priority", sortable: true, width: "3.5rem" },
      { title: "类型", key: "type", sortable: true },
      { title: "内容", key: "payload", sortable: true },
      { title: "出站", key: "action", sortable: false },
      { title: "日期", key: "time_modified", sortable: true },
      { title: "", key: "status", sortable: false, width: "1rem" },
      { title: "", key: "actions", sortable: false, width: "1rem" }
    ]);
    const dragEnabled = ref$h(false);
    const hoveredPriority = ref$h(-1);
    const dragItem = ref$h(null);
    const selected = ref$h([]);
    function dragStart(event, priority) {
      const item = props.sortedRules.find((r) => r.priority === priority);
      if (!item) {
        event.preventDefault?.();
        return;
      }
      dragItem.value = item;
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
      }
    }
    function dragOver(event, priority) {
      event.preventDefault();
      hoveredPriority.value = priority;
    }
    function drop(event, targetPriority) {
      if (dragItem.value && dragItem.value.priority !== targetPriority) {
        emit("reorder", targetPriority, dragItem.value.priority, ruleset);
      }
      dragItem.value = null;
      hoveredPriority.value = -1;
    }
    function dragEnd() {
      dragItem.value = null;
      hoveredPriority.value = -1;
    }
    function editRule(priority) {
      emit("edit", priority, ruleset);
    }
    function deleteRule(priority) {
      emit("delete", priority, ruleset);
    }
    function deleteSelected() {
      if (selected.value.length > 0) {
        emit("delete-batch", selected.value, ruleset);
        selected.value = [];
      }
    }
    function updateStatus(item, disabled) {
      emit("change-status", item.priority, disabled, ruleset);
    }
    function changeBatchStatus(disabled) {
      if (selected.value.length > 0) {
        emit("change-status-batch", selected.value, disabled, ruleset);
        selected.value = [];
      }
    }
    const rowProps = (data) => {
      const item = data.item;
      return {
        class: {
          "drop-over": item.priority === hoveredPriority.value,
          "dragging-item": dragItem.value?.priority === item.priority,
          "list-row": true,
          "text-grey": item.meta?.disabled
        },
        draggable: dragEnabled.value,
        onDragstart: (e) => dragStart(e, item.priority),
        onDragover: (e) => dragOver(e, item.priority),
        onDrop: (e) => drop(e, item.priority),
        onDragend: dragEnd
      };
    };
    return (_ctx, _cache) => {
      const _component_v_btn = _resolveComponent$p("v-btn");
      const _component_v_btn_group = _resolveComponent$p("v-btn-group");
      const _component_v_icon = _resolveComponent$p("v-icon");
      const _component_v_chip = _resolveComponent$p("v-chip");
      const _component_v_tooltip = _resolveComponent$p("v-tooltip");
      const _component_v_data_table = _resolveComponent$p("v-data-table");
      return _openBlock$p(), _createBlock$p(_component_v_data_table, {
        modelValue: selected.value,
        "onUpdate:modelValue": _cache[4] || (_cache[4] = ($event) => selected.value = $event),
        class: "px-4",
        headers: headers.value,
        search: __props.searchRule,
        items: __props.sortedRules,
        page: __props.page,
        "items-per-page": __props.itemsPerPage,
        "items-per-page-options": _unref$l(itemsPerPageOptions),
        "item-key": "priority",
        "item-value": "priority",
        "show-select": "",
        density: "compact",
        "hide-default-footer": "",
        "fixed-header": "",
        "row-props": rowProps
      }, {
        top: _withCtx$p(() => [
          selected.value.length > 0 ? (_openBlock$p(), _createBlock$p(_Teleport, {
            key: 0,
            to: "#top-rules-table-batch-actions"
          }, [
            _createVNode$p(_component_v_btn_group, {
              rounded: "",
              variant: "tonal"
            }, {
              default: _withCtx$p(() => [
                _createVNode$p(_component_v_btn, {
                  color: "success",
                  "prepend-icon": "mdi-check",
                  size: "small",
                  onClick: _cache[0] || (_cache[0] = ($event) => changeBatchStatus(false))
                }),
                _createVNode$p(_component_v_btn, {
                  color: "warning",
                  "prepend-icon": "mdi-close",
                  size: "small",
                  onClick: _cache[1] || (_cache[1] = ($event) => changeBatchStatus(true))
                }),
                _createVNode$p(_component_v_btn, {
                  color: "error",
                  "prepend-icon": "mdi-trash-can-outline",
                  size: "small",
                  onClick: deleteSelected
                })
              ]),
              _: 1
            })
          ])) : _createCommentVNode$l("", true)
        ]),
        "item.handler": _withCtx$p(({}) => [
          _createVNode$p(_component_v_icon, {
            class: "drag-handle",
            onMouseenter: _cache[2] || (_cache[2] = ($event) => dragEnabled.value = true),
            onMouseleave: _cache[3] || (_cache[3] = ($event) => dragEnabled.value = false)
          }, {
            default: _withCtx$p(() => _cache[5] || (_cache[5] = [
              _createTextVNode$p("mdi-drag-horizontal-variant ")
            ])),
            _: 1
          })
        ]),
        "item.priority": _withCtx$p(({ item }) => [
          _createVNode$p(_component_v_chip, {
            size: "x-small",
            variant: "tonal",
            color: "secondary",
            class: "font-weight-bold"
          }, {
            default: _withCtx$p(() => [
              _createTextVNode$p(_toDisplayString$m(item.priority), 1)
            ]),
            _: 2
          }, 1024)
        ]),
        "item.type": _withCtx$p(({ item }) => [
          _createVNode$p(_component_v_chip, {
            color: _unref$l(getRuleTypeColor)(item.type),
            size: "small",
            label: "",
            variant: "tonal"
          }, {
            default: _withCtx$p(() => [
              _createTextVNode$p(_toDisplayString$m(item.type), 1)
            ]),
            _: 2
          }, 1032, ["color"])
        ]),
        "item.payload": _withCtx$p(({ value }) => [
          _createElementVNode$k("small", null, _toDisplayString$m(value), 1)
        ]),
        "item.action": _withCtx$p(({ item }) => [
          _createVNode$p(_component_v_chip, {
            color: _unref$l(getActionColor)(item.action),
            size: "small",
            variant: "outlined",
            pill: ""
          }, {
            default: _withCtx$p(() => [
              _createTextVNode$p(_toDisplayString$m(item.action), 1)
            ]),
            _: 2
          }, 1032, ["color"])
        ]),
        "item.time_modified": _withCtx$p(({ item }) => [
          _createElementVNode$k("small", null, _toDisplayString$m(item.meta?.time_modified ? _unref$l(timestampToDate)(item.meta.time_modified) : ""), 1)
        ]),
        "item.status": _withCtx$p(({ item }) => [
          _createElementVNode$k("div", _hoisted_1$h, [
            _createVNode$p(_component_v_icon, {
              color: item.meta.disabled ? "grey" : "success",
              class: "mr-1"
            }, {
              default: _withCtx$p(() => [
                _createTextVNode$p(_toDisplayString$m(item.meta.disabled ? "mdi-close-circle-outline" : "mdi-check-circle-outline"), 1)
              ]),
              _: 2
            }, 1032, ["color"]),
            item.meta.invisible_to && item.meta.invisible_to.length > 0 ? (_openBlock$p(), _createBlock$p(_component_v_tooltip, {
              key: 0,
              text: "已配置可见性限制",
              location: "top"
            }, {
              activator: _withCtx$p(({ props: props2 }) => [
                _createVNode$p(_component_v_icon, _mergeProps$j(props2, {
                  size: "small",
                  color: "warning"
                }), {
                  default: _withCtx$p(() => _cache[6] || (_cache[6] = [
                    _createTextVNode$p(" mdi-eye-off-outline ")
                  ])),
                  _: 2
                }, 1040)
              ]),
              _: 1
            })) : _createCommentVNode$l("", true)
          ])
        ]),
        "item.actions": _withCtx$p(({ item }) => [
          _createVNode$p(_sfc_main$u, {
            rule: item,
            onEdit: ($event) => editRule(item.priority),
            onDelete: ($event) => deleteRule(item.priority),
            onChangeStatus: (disabled) => updateStatus(item, disabled),
            onEditVisibility: ($event) => emit("editVisibility", item.priority, ruleset)
          }, null, 8, ["rule", "onEdit", "onDelete", "onChangeStatus", "onEditVisibility"])
        ]),
        _: 1
      }, 8, ["modelValue", "headers", "search", "items", "page", "items-per-page", "items-per-page-options"]);
    };
  }
});

const {defineComponent:_defineComponent$o} = await importShared('vue');

const {createTextVNode:_createTextVNode$o,resolveComponent:_resolveComponent$o,withCtx:_withCtx$o,createVNode:_createVNode$o,unref:_unref$k,createElementVNode:_createElementVNode$j,openBlock:_openBlock$o,createBlock:_createBlock$o} = await importShared('vue');

const {ref: ref$g} = await importShared('vue');
const _sfc_main$o = /* @__PURE__ */ _defineComponent$o({
  __name: "ImportRuleDialog",
  props: {
    modelValue: { type: Boolean },
    api: {}
  },
  emits: ["update:modelValue", "refresh", "show-snackbar", "show-error"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const editorOptions = {
      enableBasicAutocompletion: true,
      enableSnippets: true,
      enableLiveAutocompletion: true,
      showLineNumbers: true,
      tabSize: 2
    };
    const rulesPlaceholder = ref$g(
      `rules:
  - DOMAIN,gemini.google.com,Openai`
    );
    const importRuleTypes = ["YAML"];
    const importRuleLoading = ref$g(false);
    const importRules = ref$g({
      type: "YAML",
      payload: ""
    });
    function close() {
      emit("update:modelValue", false);
    }
    async function importRule() {
      try {
        importRuleLoading.value = true;
        const requestData = {
          vehicle: importRules.value.type,
          payload: importRules.value.payload
        };
        const result = await props.api.post("/plugin/ClashRuleProvider/import", requestData);
        if (!result.success) {
          emit("show-error", "规则导入失败: " + (result.message || "未知错误"));
          emit("show-snackbar", {
            show: true,
            message: "规则导入失败",
            color: "error"
          });
          return;
        }
        close();
        emit("refresh");
        emit("show-snackbar", {
          show: true,
          message: "规则导入成功",
          color: "success"
        });
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", "导入规则失败: " + (err.message || "未知错误"));
        }
        emit("show-snackbar", {
          show: true,
          message: "导入规则失败",
          color: "error"
        });
      } finally {
        importRuleLoading.value = false;
      }
    }
    return (_ctx, _cache) => {
      const _component_v_card_title = _resolveComponent$o("v-card-title");
      const _component_v_select = _resolveComponent$o("v-select");
      const _component_v_alert = _resolveComponent$o("v-alert");
      const _component_v_card_text = _resolveComponent$o("v-card-text");
      const _component_v_spacer = _resolveComponent$o("v-spacer");
      const _component_v_btn = _resolveComponent$o("v-btn");
      const _component_v_card_actions = _resolveComponent$o("v-card-actions");
      const _component_v_card = _resolveComponent$o("v-card");
      const _component_v_dialog = _resolveComponent$o("v-dialog");
      return _openBlock$o(), _createBlock$o(_component_v_dialog, {
        "model-value": _ctx.modelValue,
        "max-width": "40rem",
        "onUpdate:modelValue": _cache[2] || (_cache[2] = ($event) => emit("update:modelValue", $event))
      }, {
        default: _withCtx$o(() => [
          _createVNode$o(_component_v_card, null, {
            default: _withCtx$o(() => [
              _createVNode$o(_component_v_card_title, null, {
                default: _withCtx$o(() => _cache[3] || (_cache[3] = [
                  _createTextVNode$o("导入规则")
                ])),
                _: 1
              }),
              _createVNode$o(_component_v_card_text, { style: { "max-height": "900px", "overflow-y": "auto" } }, {
                default: _withCtx$o(() => [
                  _createVNode$o(_component_v_select, {
                    modelValue: importRules.value.type,
                    "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => importRules.value.type = $event),
                    items: importRuleTypes,
                    label: "内容格式",
                    required: "",
                    class: "mb-4"
                  }, null, 8, ["modelValue"]),
                  _createVNode$o(_unref$k(VAceEditor), {
                    value: importRules.value.payload,
                    "onUpdate:value": _cache[1] || (_cache[1] = ($event) => importRules.value.payload = $event),
                    lang: "yaml",
                    theme: "monokai",
                    options: editorOptions,
                    placeholder: rulesPlaceholder.value,
                    style: { "height": "30rem", "width": "100%", "margin-bottom": "16px" }
                  }, null, 8, ["value", "placeholder"]),
                  _createVNode$o(_component_v_alert, {
                    type: "info",
                    dense: "",
                    class: "mb-4",
                    variant: "tonal"
                  }, {
                    default: _withCtx$o(() => _cache[4] || (_cache[4] = [
                      _createTextVNode$o(" 请输入 Clash 规则中的 "),
                      _createElementVNode$j("strong", null, "rules", -1),
                      _createTextVNode$o(" 字段，例如："),
                      _createElementVNode$j("br", null, null, -1),
                      _createElementVNode$j("code", null, [
                        _createTextVNode$o("rules:"),
                        _createElementVNode$j("br"),
                        _createTextVNode$o("- DOMAIN,gemini.google.com,Openai")
                      ], -1)
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              }),
              _createVNode$o(_component_v_card_actions, null, {
                default: _withCtx$o(() => [
                  _createVNode$o(_component_v_spacer),
                  _createVNode$o(_component_v_btn, {
                    color: "secondary",
                    onClick: close
                  }, {
                    default: _withCtx$o(() => _cache[5] || (_cache[5] = [
                      _createTextVNode$o("取消")
                    ])),
                    _: 1
                  }),
                  _createVNode$o(_component_v_btn, {
                    color: "primary",
                    loading: importRuleLoading.value,
                    onClick: importRule
                  }, {
                    default: _withCtx$o(() => _cache[6] || (_cache[6] = [
                      _createTextVNode$o("导入 ")
                    ])),
                    _: 1
                  }, 8, ["loading"])
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _: 1
      }, 8, ["model-value"]);
    };
  }
});

const {defineComponent:_defineComponent$n} = await importShared('vue');

const {resolveComponent:_resolveComponent$n,createVNode:_createVNode$n,withCtx:_withCtx$n,createElementVNode:_createElementVNode$i,renderList:_renderList$8,Fragment:_Fragment$8,openBlock:_openBlock$n,createElementBlock:_createElementBlock$9,createBlock:_createBlock$n,unref:_unref$j,toDisplayString:_toDisplayString$l,createTextVNode:_createTextVNode$n,mergeProps:_mergeProps$i,createCommentVNode:_createCommentVNode$k} = await importShared('vue');

const _hoisted_1$g = { class: "mb-2 position-relative" };
const _hoisted_2$c = { class: "pa-4" };
const _hoisted_3$c = { class: "d-none d-sm-flex clash-data-table" };
const _hoisted_4$a = { class: "d-sm-none" };
const _hoisted_5$7 = {
  class: "pa-4",
  style: { "min-height": "4rem" }
};
const {computed: computed$6,ref: ref$f,toRaw: toRaw$6} = await importShared('vue');
const _sfc_main$n = /* @__PURE__ */ _defineComponent$n({
  __name: "TopRulesTab",
  props: {
    rules: {},
    api: {},
    ruleProviderNames: {},
    geoRules: {},
    customOutbounds: {}
  },
  emits: ["refresh", "show-snackbar", "show-error", "edit-visibility"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const searchTopRule = ref$f("");
    const page = ref$f(1);
    const itemsPerPage = ref$f(10);
    const loading = ref$f(false);
    const ruleDialogVisible = ref$f(false);
    const importRuleDialog = ref$f(false);
    const editingPriority = ref$f(null);
    const currentRule = ref$f({ ...defaultRule });
    const editingType = ref$f("top");
    const filteredRules = computed$6(() => {
      if (!searchTopRule.value) return props.rules;
      const keyword = searchTopRule.value.toLowerCase();
      return props.rules.filter(
        (item) => Object.values(item).some((val) => String(val).toLowerCase().includes(keyword))
      );
    });
    const pageCount = computed$6(() => {
      if (itemsPerPage.value === -1) {
        return 1;
      }
      return Math.ceil(filteredRules.value.length / itemsPerPage.value);
    });
    const paginatedTopRules = computed$6(() => {
      const start = (page.value - 1) * itemsPerPage.value;
      const end = start + itemsPerPage.value;
      return filteredRules.value.slice(start, end);
    });
    function openImportRuleDialog() {
      importRuleDialog.value = true;
    }
    function openAddRuleDialog() {
      editingPriority.value = null;
      const nextPriority = props.rules.length > 0 ? props.rules[props.rules.length - 1].priority + 1 : 0;
      currentRule.value = { ...defaultRule };
      currentRule.value.priority = nextPriority;
      ruleDialogVisible.value = true;
    }
    function closeRuleDialog() {
      ruleDialogVisible.value = false;
    }
    function editRule(priority) {
      const rule = props.rules.find((r) => r.priority === priority);
      if (rule) {
        editingPriority.value = priority;
        currentRule.value = structuredClone(toRaw$6(rule));
        ruleDialogVisible.value = true;
      }
    }
    async function deleteRule(priority) {
      loading.value = true;
      try {
        await props.api.delete(`/plugin/ClashRuleProvider/rules/top/${priority}`);
        emit("refresh", ["top", "ruleset"]);
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", err.message || "删除规则失败");
        }
      } finally {
        loading.value = false;
      }
    }
    async function deleteRules(priorities) {
      loading.value = true;
      try {
        await props.api.delete("/plugin/ClashRuleProvider/rules/top", {
          data: { rules_priority: priorities }
        });
        emit("refresh", ["top", "ruleset"]);
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", err.message || "批量删除规则失败");
        }
      } finally {
        loading.value = false;
      }
    }
    async function handleReorderRule(targetPriority, movedPriority) {
      loading.value = true;
      try {
        await props.api.put(`/plugin/ClashRuleProvider/reorder-rules/top/${targetPriority}`, {
          moved_priority: movedPriority
        });
        emit("refresh", ["top", "ruleset"]);
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", err.message || "重排序失败");
        }
      } finally {
        loading.value = false;
      }
    }
    async function handleStatusChange(priority, disabled) {
      loading.value = true;
      try {
        await props.api.post(`/plugin/ClashRuleProvider/rules/top/metadata/disabled`, {
          [priority]: disabled
        });
        emit("refresh", ["top", "ruleset"]);
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", err.message || "更新规则状态失败");
        }
      } finally {
        loading.value = false;
      }
    }
    async function handleBatchStatusChange(priorities, disabled) {
      loading.value = true;
      try {
        const payload = priorities.reduce((acc, p) => ({ ...acc, [p]: disabled }), {});
        await props.api.post(`/plugin/ClashRuleProvider/rules/top/metadata/disabled`, payload);
        emit("refresh", ["top", "ruleset"]);
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", err.message || "批量更新规则状态失败");
        }
      } finally {
        loading.value = false;
      }
    }
    function editVisibility(priority, type) {
      const rule = props.rules.find((r) => r.priority === priority);
      if (!rule) {
        emit("show-error", "Rule not found");
        return;
      }
      emit(
        "edit-visibility",
        rule.meta,
        `/plugin/ClashRuleProvider/rules/${type}/${priority}/meta`,
        type
      );
    }
    return (_ctx, _cache) => {
      const _component_v_progress_circular = _resolveComponent$n("v-progress-circular");
      const _component_v_overlay = _resolveComponent$n("v-overlay");
      const _component_v_text_field = _resolveComponent$n("v-text-field");
      const _component_v_col = _resolveComponent$n("v-col");
      const _component_v_btn = _resolveComponent$n("v-btn");
      const _component_v_btn_group = _resolveComponent$n("v-btn-group");
      const _component_v_row = _resolveComponent$n("v-row");
      const _component_v_pagination = _resolveComponent$n("v-pagination");
      const _component_v_list_item_title = _resolveComponent$n("v-list-item-title");
      const _component_v_list_item = _resolveComponent$n("v-list-item");
      const _component_v_list = _resolveComponent$n("v-list");
      const _component_v_menu = _resolveComponent$n("v-menu");
      const _component_v_divider = _resolveComponent$n("v-divider");
      return _openBlock$n(), _createElementBlock$9("div", _hoisted_1$g, [
        _createVNode$n(_component_v_overlay, {
          modelValue: loading.value,
          "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => loading.value = $event),
          contained: "",
          class: "align-center justify-center"
        }, {
          default: _withCtx$n(() => [
            _createVNode$n(_component_v_progress_circular, {
              indeterminate: "",
              color: "primary"
            })
          ]),
          _: 1
        }, 8, ["modelValue"]),
        _createElementVNode$i("div", _hoisted_2$c, [
          _createVNode$n(_component_v_row, {
            align: "center",
            "no-gutters": ""
          }, {
            default: _withCtx$n(() => [
              _createVNode$n(_component_v_col, {
                cols: "8",
                sm: "6",
                class: "d-flex justify-start"
              }, {
                default: _withCtx$n(() => [
                  _createVNode$n(_component_v_text_field, {
                    modelValue: searchTopRule.value,
                    "onUpdate:modelValue": _cache[1] || (_cache[1] = ($event) => searchTopRule.value = $event),
                    label: "搜索规则",
                    clearable: "",
                    density: "compact",
                    variant: "solo-filled",
                    "hide-details": "",
                    class: "search-field",
                    "prepend-inner-icon": "mdi-magnify",
                    flat: "",
                    rounded: "pill",
                    "single-line": "",
                    disabled: loading.value
                  }, null, 8, ["modelValue", "disabled"])
                ]),
                _: 1
              }),
              _createVNode$n(_component_v_col, {
                cols: "4",
                sm: "6",
                class: "d-flex justify-end"
              }, {
                default: _withCtx$n(() => [
                  _createVNode$n(_component_v_btn_group, {
                    divided: "",
                    variant: "outlined",
                    rounded: ""
                  }, {
                    default: _withCtx$n(() => [
                      _createVNode$n(_component_v_btn, {
                        icon: "mdi-import",
                        disabled: loading.value,
                        onClick: openImportRuleDialog
                      }, null, 8, ["disabled"]),
                      _createVNode$n(_component_v_btn, {
                        icon: "mdi-plus",
                        disabled: loading.value,
                        onClick: openAddRuleDialog
                      }, null, 8, ["disabled"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _createElementVNode$i("div", _hoisted_3$c, [
          _createVNode$n(_sfc_main$p, {
            "sorted-rules": _ctx.rules,
            page: page.value,
            "items-per-page": itemsPerPage.value,
            "search-rule": searchTopRule.value,
            onEdit: editRule,
            onDelete: deleteRule,
            onDeleteBatch: deleteRules,
            onReorder: handleReorderRule,
            onChangeStatus: handleStatusChange,
            onChangeStatusBatch: handleBatchStatusChange,
            onEditVisibility: editVisibility
          }, null, 8, ["sorted-rules", "page", "items-per-page", "search-rule"])
        ]),
        _createElementVNode$i("div", _hoisted_4$a, [
          _createVNode$n(_component_v_row, null, {
            default: _withCtx$n(() => [
              (_openBlock$n(true), _createElementBlock$9(_Fragment$8, null, _renderList$8(paginatedTopRules.value, (item) => {
                return _openBlock$n(), _createBlock$n(_component_v_col, {
                  key: item.priority,
                  cols: "12"
                }, {
                  default: _withCtx$n(() => [
                    _createVNode$n(RuleCard, {
                      ruleset: "top",
                      rule: item,
                      onDelete: deleteRule,
                      onEdit: editRule,
                      onChangeStatus: handleStatusChange,
                      onEditVisibility: editVisibility
                    }, null, 8, ["rule"])
                  ]),
                  _: 2
                }, 1024);
              }), 128))
            ]),
            _: 1
          })
        ]),
        _createElementVNode$i("div", _hoisted_5$7, [
          _createVNode$n(_component_v_row, {
            align: "center",
            "no-gutters": ""
          }, {
            default: _withCtx$n(() => [
              _createVNode$n(_component_v_col, {
                cols: "2",
                md: "2"
              }, {
                default: _withCtx$n(() => _cache[12] || (_cache[12] = [
                  _createElementVNode$i("div", { id: "top-rules-table-batch-actions" }, null, -1)
                ])),
                _: 1
              }),
              _createVNode$n(_component_v_col, {
                cols: "8",
                md: "8",
                class: "d-flex justify-center"
              }, {
                default: _withCtx$n(() => [
                  _createVNode$n(_component_v_pagination, {
                    modelValue: page.value,
                    "onUpdate:modelValue": _cache[2] || (_cache[2] = ($event) => page.value = $event),
                    length: pageCount.value,
                    "total-visible": "5",
                    rounded: "circle",
                    class: "d-none d-sm-flex my-0",
                    disabled: loading.value
                  }, null, 8, ["modelValue", "length", "disabled"]),
                  _createVNode$n(_component_v_pagination, {
                    modelValue: page.value,
                    "onUpdate:modelValue": _cache[3] || (_cache[3] = ($event) => page.value = $event),
                    length: pageCount.value,
                    "total-visible": "0",
                    rounded: "circle",
                    class: "d-sm-none my-0",
                    disabled: loading.value
                  }, null, 8, ["modelValue", "length", "disabled"])
                ]),
                _: 1
              }),
              _createVNode$n(_component_v_col, {
                cols: "2",
                md: "2",
                class: "d-flex justify-end"
              }, {
                default: _withCtx$n(() => [
                  _createVNode$n(_component_v_menu, null, {
                    activator: _withCtx$n(({ props: props2 }) => [
                      _createVNode$n(_component_v_btn, _mergeProps$i(props2, {
                        icon: "",
                        rounded: "circle",
                        variant: "tonal",
                        disabled: loading.value
                      }), {
                        default: _withCtx$n(() => [
                          _createTextVNode$n(_toDisplayString$l(_unref$j(pageTitle)(itemsPerPage.value)), 1)
                        ]),
                        _: 2
                      }, 1040, ["disabled"])
                    ]),
                    default: _withCtx$n(() => [
                      _createVNode$n(_component_v_list, null, {
                        default: _withCtx$n(() => [
                          (_openBlock$n(true), _createElementBlock$9(_Fragment$8, null, _renderList$8(_unref$j(itemsPerPageOptions), (item, index) => {
                            return _openBlock$n(), _createBlock$n(_component_v_list_item, {
                              key: index,
                              value: item.value,
                              onClick: ($event) => itemsPerPage.value = item.value
                            }, {
                              default: _withCtx$n(() => [
                                _createVNode$n(_component_v_list_item_title, null, {
                                  default: _withCtx$n(() => [
                                    _createTextVNode$n(_toDisplayString$l(item.title), 1)
                                  ]),
                                  _: 2
                                }, 1024)
                              ]),
                              _: 2
                            }, 1032, ["value", "onClick"]);
                          }), 128))
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _createVNode$n(_component_v_divider),
        _cache[13] || (_cache[13] = _createElementVNode$i("div", { class: "text-caption text-grey mt-2" }, " *置顶规则用于管理来自规则集的匹配规则，这些规则会动态更新。 ", -1)),
        _cache[14] || (_cache[14] = _createElementVNode$i("div", { class: "text-caption text-grey mt-2" }, "*对置顶规则的修改只有Clash更新配置后才会生效。", -1)),
        ruleDialogVisible.value ? (_openBlock$n(), _createBlock$n(_sfc_main$r, {
          key: 0,
          modelValue: ruleDialogVisible.value,
          "onUpdate:modelValue": _cache[4] || (_cache[4] = ($event) => ruleDialogVisible.value = $event),
          "initial-rule": currentRule.value,
          "is-adding": editingPriority.value === null,
          "editing-type": editingType.value,
          "rule-provider-names": _ctx.ruleProviderNames,
          "geo-rules": _ctx.geoRules,
          "custom-outbounds": _ctx.customOutbounds,
          api: _ctx.api,
          onRefresh: _cache[5] || (_cache[5] = (v) => emit("refresh", v)),
          onShowSnackbar: _cache[6] || (_cache[6] = (val) => emit("show-snackbar", val)),
          onShowError: _cache[7] || (_cache[7] = (msg) => emit("show-error", msg)),
          onClose: closeRuleDialog
        }, null, 8, ["modelValue", "initial-rule", "is-adding", "editing-type", "rule-provider-names", "geo-rules", "custom-outbounds", "api"])) : _createCommentVNode$k("", true),
        importRuleDialog.value ? (_openBlock$n(), _createBlock$n(_sfc_main$o, {
          key: 1,
          modelValue: importRuleDialog.value,
          "onUpdate:modelValue": _cache[8] || (_cache[8] = ($event) => importRuleDialog.value = $event),
          api: _ctx.api,
          onRefresh: _cache[9] || (_cache[9] = ($event) => emit("refresh", ["top"])),
          onShowSnackbar: _cache[10] || (_cache[10] = (val) => emit("show-snackbar", val)),
          onShowError: _cache[11] || (_cache[11] = (msg) => emit("show-error", msg))
        }, null, 8, ["modelValue", "api"])) : _createCommentVNode$k("", true)
      ]);
    };
  }
});

const {defineComponent:_defineComponent$m} = await importShared('vue');

const {createTextVNode:_createTextVNode$m,resolveComponent:_resolveComponent$m,withCtx:_withCtx$m,createVNode:_createVNode$m,mergeProps:_mergeProps$h,unref:_unref$i,toDisplayString:_toDisplayString$k,openBlock:_openBlock$m,createBlock:_createBlock$m,createCommentVNode:_createCommentVNode$j} = await importShared('vue');
const _sfc_main$m = /* @__PURE__ */ _defineComponent$m({
  __name: "ProxyGroupActionMenu",
  props: {
    proxyGroup: {
      type: Object,
      required: true
    }
  },
  emits: ["showYaml", "edit", "delete", "deletePatch", "changeStatus", "editVisibility"],
  setup(__props, { emit: __emit }) {
    const emit = __emit;
    return (_ctx, _cache) => {
      const _component_v_icon = _resolveComponent$m("v-icon");
      const _component_v_btn = _resolveComponent$m("v-btn");
      const _component_v_list_item_title = _resolveComponent$m("v-list-item-title");
      const _component_v_list_item = _resolveComponent$m("v-list-item");
      const _component_v_list = _resolveComponent$m("v-list");
      const _component_v_menu = _resolveComponent$m("v-menu");
      return _openBlock$m(), _createBlock$m(_component_v_menu, { "min-width": "120" }, {
        activator: _withCtx$m(({ props }) => [
          _createVNode$m(_component_v_btn, _mergeProps$h({
            color: "secondary",
            icon: "",
            size: "small",
            variant: "text"
          }, props), {
            default: _withCtx$m(() => [
              _createVNode$m(_component_v_icon, null, {
                default: _withCtx$m(() => _cache[6] || (_cache[6] = [
                  _createTextVNode$m("mdi-dots-vertical")
                ])),
                _: 1
              })
            ]),
            _: 2
          }, 1040)
        ]),
        default: _withCtx$m(() => [
          _createVNode$m(_component_v_list, { density: "compact" }, {
            default: _withCtx$m(() => [
              _unref$i(isManual)(__props.proxyGroup.meta.source) ? (_openBlock$m(), _createBlock$m(_component_v_list_item, {
                key: 0,
                onClick: _cache[0] || (_cache[0] = ($event) => emit("changeStatus", !__props.proxyGroup.meta.disabled))
              }, {
                prepend: _withCtx$m(() => [
                  _createVNode$m(_component_v_icon, {
                    size: "small",
                    color: __props.proxyGroup.meta.disabled ? "success" : "grey"
                  }, {
                    default: _withCtx$m(() => [
                      _createTextVNode$m(_toDisplayString$k(__props.proxyGroup.meta.disabled ? "mdi-play-circle-outline" : "mdi-stop-circle-outline"), 1)
                    ]),
                    _: 1
                  }, 8, ["color"])
                ]),
                default: _withCtx$m(() => [
                  _createVNode$m(_component_v_list_item_title, null, {
                    default: _withCtx$m(() => [
                      _createTextVNode$m(_toDisplayString$k(__props.proxyGroup.meta.disabled ? "启用" : "禁用"), 1)
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })) : _createCommentVNode$j("", true),
              _createVNode$m(_component_v_list_item, {
                onClick: _cache[1] || (_cache[1] = ($event) => emit("showYaml"))
              }, {
                prepend: _withCtx$m(() => [
                  _createVNode$m(_component_v_icon, {
                    size: "small",
                    color: "info"
                  }, {
                    default: _withCtx$m(() => _cache[7] || (_cache[7] = [
                      _createTextVNode$m("mdi-code-json")
                    ])),
                    _: 1
                  })
                ]),
                default: _withCtx$m(() => [
                  _createVNode$m(_component_v_list_item_title, null, {
                    default: _withCtx$m(() => _cache[8] || (_cache[8] = [
                      _createTextVNode$m("查看")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              }),
              _unref$i(isManual)(__props.proxyGroup.meta.source) || _unref$i(isRegion)(__props.proxyGroup.meta.source) ? (_openBlock$m(), _createBlock$m(_component_v_list_item, {
                key: 1,
                onClick: _cache[2] || (_cache[2] = ($event) => emit("edit"))
              }, {
                prepend: _withCtx$m(() => [
                  _createVNode$m(_component_v_icon, {
                    size: "small",
                    color: "primary"
                  }, {
                    default: _withCtx$m(() => _cache[9] || (_cache[9] = [
                      _createTextVNode$m("mdi-file-edit-outline")
                    ])),
                    _: 1
                  })
                ]),
                default: _withCtx$m(() => [
                  _createVNode$m(_component_v_list_item_title, null, {
                    default: _withCtx$m(() => _cache[10] || (_cache[10] = [
                      _createTextVNode$m("编辑")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              })) : _createCommentVNode$j("", true),
              _unref$i(isManual)(__props.proxyGroup.meta.source) ? (_openBlock$m(), _createBlock$m(_component_v_list_item, {
                key: 2,
                onClick: _cache[3] || (_cache[3] = ($event) => emit("editVisibility"))
              }, {
                prepend: _withCtx$m(() => [
                  _createVNode$m(_component_v_icon, {
                    size: "small",
                    color: "warning"
                  }, {
                    default: _withCtx$m(() => _cache[11] || (_cache[11] = [
                      _createTextVNode$m("mdi-eye-off-outline")
                    ])),
                    _: 1
                  })
                ]),
                default: _withCtx$m(() => [
                  _createVNode$m(_component_v_list_item_title, null, {
                    default: _withCtx$m(() => _cache[12] || (_cache[12] = [
                      _createTextVNode$m("隐藏")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              })) : _createCommentVNode$j("", true),
              __props.proxyGroup.meta.patched ? (_openBlock$m(), _createBlock$m(_component_v_list_item, {
                key: 3,
                onClick: _cache[4] || (_cache[4] = ($event) => emit("deletePatch"))
              }, {
                prepend: _withCtx$m(() => [
                  _createVNode$m(_component_v_icon, {
                    size: "small",
                    color: "error"
                  }, {
                    default: _withCtx$m(() => _cache[13] || (_cache[13] = [
                      _createTextVNode$m("mdi-close-box-outline")
                    ])),
                    _: 1
                  })
                ]),
                default: _withCtx$m(() => [
                  _createVNode$m(_component_v_list_item_title, null, {
                    default: _withCtx$m(() => _cache[14] || (_cache[14] = [
                      _createTextVNode$m("删除补丁")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              })) : _createCommentVNode$j("", true),
              _unref$i(isManual)(__props.proxyGroup.meta.source) ? (_openBlock$m(), _createBlock$m(_component_v_list_item, {
                key: 4,
                onClick: _cache[5] || (_cache[5] = ($event) => emit("delete"))
              }, {
                prepend: _withCtx$m(() => [
                  _createVNode$m(_component_v_icon, {
                    size: "small",
                    color: "error"
                  }, {
                    default: _withCtx$m(() => _cache[15] || (_cache[15] = [
                      _createTextVNode$m("mdi-trash-can-outline")
                    ])),
                    _: 1
                  })
                ]),
                default: _withCtx$m(() => [
                  _createVNode$m(_component_v_list_item_title, null, {
                    default: _withCtx$m(() => _cache[16] || (_cache[16] = [
                      _createTextVNode$m("删除")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              })) : _createCommentVNode$j("", true)
            ]),
            _: 1
          })
        ]),
        _: 1
      });
    };
  }
});

const {defineComponent:_defineComponent$l} = await importShared('vue');

const {unref:_unref$h,toDisplayString:_toDisplayString$j,createTextVNode:_createTextVNode$l,resolveComponent:_resolveComponent$l,withCtx:_withCtx$l,createVNode:_createVNode$l,mergeProps:_mergeProps$g,openBlock:_openBlock$l,createBlock:_createBlock$l,createCommentVNode:_createCommentVNode$i,createElementVNode:_createElementVNode$h} = await importShared('vue');

const _hoisted_1$f = { class: "d-flex align-center" };
const {ref: ref$e} = await importShared('vue');
const _sfc_main$l = /* @__PURE__ */ _defineComponent$l({
  __name: "ProxyGroupsTable",
  props: {
    proxyGroups: {
      type: Array,
      required: true
    },
    page: {
      type: Number,
      required: true
    },
    itemsPerPage: {
      type: Number,
      required: true
    },
    search: String
  },
  emits: ["copyToClipboard", "showYaml", "editProxyGroup", "deleteProxyGroup", "deletePatch", "changeStatus", "editVisibility"],
  setup(__props, { emit: __emit }) {
    const emit = __emit;
    const proxyGroupHeaders = ref$e([
      { title: "名称", key: "name", sortable: true },
      { title: "类型", key: "type", sortable: false },
      { title: "来源", key: "source", sortable: false },
      { title: "", key: "status", sortable: false, width: "1.5rem" },
      { title: "", key: "actions", sortable: false, width: "1rem" }
    ]);
    return (_ctx, _cache) => {
      const _component_v_chip = _resolveComponent$l("v-chip");
      const _component_v_icon = _resolveComponent$l("v-icon");
      const _component_v_tooltip = _resolveComponent$l("v-tooltip");
      const _component_v_data_table = _resolveComponent$l("v-data-table");
      return _openBlock$l(), _createBlock$l(_component_v_data_table, {
        class: "px-4",
        headers: proxyGroupHeaders.value,
        search: __props.search,
        items: __props.proxyGroups,
        page: __props.page,
        "items-per-page": __props.itemsPerPage,
        "items-per-page-options": _unref$h(itemsPerPageOptions),
        density: "compact",
        "hide-default-footer": "",
        "fixed-header": "",
        "item-key": "name"
      }, {
        "item.name": _withCtx$l(({ item }) => [
          _createVNode$l(_component_v_chip, {
            size: "small",
            pill: "",
            color: "secondary"
          }, {
            default: _withCtx$l(() => [
              _createTextVNode$l(_toDisplayString$j(item.data.name), 1)
            ]),
            _: 2
          }, 1024)
        ]),
        "item.type": _withCtx$l(({ item }) => [
          _createVNode$l(_component_v_chip, {
            color: _unref$h(getProxyGroupTypeColor)(item.data.type),
            size: "small",
            label: "",
            variant: "tonal"
          }, {
            default: _withCtx$l(() => [
              _createTextVNode$l(_toDisplayString$j(item.data.type), 1)
            ]),
            _: 2
          }, 1032, ["color"])
        ]),
        "item.source": _withCtx$l(({ item }) => [
          _createVNode$l(_component_v_chip, {
            size: "small",
            color: _unref$h(getSourceColor)(item.meta.source),
            variant: "outlined"
          }, {
            default: _withCtx$l(() => [
              _createTextVNode$l(_toDisplayString$j(item.meta.source), 1)
            ]),
            _: 2
          }, 1032, ["color"])
        ]),
        "item.status": _withCtx$l(({ item }) => [
          _createElementVNode$h("div", _hoisted_1$f, [
            _createVNode$l(_component_v_icon, {
              color: item.meta.disabled ? "grey" : "success",
              class: "mr-1"
            }, {
              default: _withCtx$l(() => [
                _createTextVNode$l(_toDisplayString$j(item.meta.disabled ? "mdi-close-circle-outline" : "mdi-check-circle-outline"), 1)
              ]),
              _: 2
            }, 1032, ["color"]),
            item.meta.invisible_to && item.meta.invisible_to.length > 0 ? (_openBlock$l(), _createBlock$l(_component_v_tooltip, {
              key: 0,
              text: "已配置可见性限制",
              location: "top"
            }, {
              activator: _withCtx$l(({ props }) => [
                _createVNode$l(_component_v_icon, _mergeProps$g(props, {
                  size: "small",
                  color: "warning"
                }), {
                  default: _withCtx$l(() => _cache[0] || (_cache[0] = [
                    _createTextVNode$l(" mdi-eye-off-outline ")
                  ])),
                  _: 2
                }, 1040)
              ]),
              _: 1
            })) : _createCommentVNode$i("", true),
            item.meta.patched ? (_openBlock$l(), _createBlock$l(_component_v_tooltip, {
              key: 1,
              text: "已应用补丁",
              location: "top"
            }, {
              activator: _withCtx$l(({ props }) => [
                _createVNode$l(_component_v_icon, _mergeProps$g(props, {
                  size: "small",
                  color: "info"
                }), {
                  default: _withCtx$l(() => _cache[1] || (_cache[1] = [
                    _createTextVNode$l(" mdi-auto-fix ")
                  ])),
                  _: 2
                }, 1040)
              ]),
              _: 1
            })) : _createCommentVNode$i("", true)
          ])
        ]),
        "item.actions": _withCtx$l(({ item }) => [
          _createVNode$l(_sfc_main$m, {
            "proxy-group": item,
            onChangeStatus: (disabled) => emit("changeStatus", item.data.name, disabled),
            onShowYaml: ($event) => emit("showYaml", item.data),
            onEdit: ($event) => emit("editProxyGroup", item.data.name),
            onDelete: ($event) => emit("deleteProxyGroup", item.data.name),
            onDeletePatch: ($event) => emit("deletePatch", item.data.name),
            onEditVisibility: ($event) => emit("editVisibility", item.data.name)
          }, null, 8, ["proxy-group", "onChangeStatus", "onShowYaml", "onEdit", "onDelete", "onDeletePatch", "onEditVisibility"])
        ]),
        _: 1
      }, 8, ["headers", "search", "items", "page", "items-per-page", "items-per-page-options"]);
    };
  }
});

const {defineComponent:_defineComponent$k} = await importShared('vue');

const {toDisplayString:_toDisplayString$i,createElementVNode:_createElementVNode$g,createTextVNode:_createTextVNode$k,resolveComponent:_resolveComponent$k,mergeProps:_mergeProps$f,withCtx:_withCtx$k,createVNode:_createVNode$k,openBlock:_openBlock$k,createBlock:_createBlock$k,createCommentVNode:_createCommentVNode$h,unref:_unref$g} = await importShared('vue');

const _hoisted_1$e = { class: "d-flex justify-space-between align-center px-4 pt-3" };
const _hoisted_2$b = ["title"];
const _hoisted_3$b = { class: "d-flex align-center" };
const _sfc_main$k = /* @__PURE__ */ _defineComponent$k({
  __name: "ProxyGroupCard",
  props: {
    proxyGroupData: {
      type: Object,
      required: true
    }
  },
  emits: ["showYaml", "editProxyGroup", "deleteProxyGroup", "deletePatch", "changeStatus", "editVisibility"],
  setup(__props, { emit: __emit }) {
    const emit = __emit;
    return (_ctx, _cache) => {
      const _component_v_icon = _resolveComponent$k("v-icon");
      const _component_v_tooltip = _resolveComponent$k("v-tooltip");
      const _component_v_chip = _resolveComponent$k("v-chip");
      const _component_v_col = _resolveComponent$k("v-col");
      const _component_v_row = _resolveComponent$k("v-row");
      const _component_v_card_text = _resolveComponent$k("v-card-text");
      const _component_v_divider = _resolveComponent$k("v-divider");
      const _component_v_spacer = _resolveComponent$k("v-spacer");
      const _component_v_card_actions = _resolveComponent$k("v-card-actions");
      const _component_v_card = _resolveComponent$k("v-card");
      return _openBlock$k(), _createBlock$k(_component_v_card, {
        rounded: "lg",
        elevation: "2",
        class: "proxy-group-card h-100 transition-swing",
        variant: "tonal"
      }, {
        default: _withCtx$k(() => [
          _createElementVNode$g("div", _hoisted_1$e, [
            _createElementVNode$g("span", {
              class: "font-weight-bold text-truncate",
              title: __props.proxyGroupData.data.name
            }, _toDisplayString$i(__props.proxyGroupData.data.name), 9, _hoisted_2$b),
            _createElementVNode$g("div", _hoisted_3$b, [
              __props.proxyGroupData.meta.invisible_to && __props.proxyGroupData.meta.invisible_to.length > 0 ? (_openBlock$k(), _createBlock$k(_component_v_tooltip, {
                key: 0,
                text: "已配置可见性限制",
                location: "top"
              }, {
                activator: _withCtx$k(({ props }) => [
                  _createVNode$k(_component_v_icon, _mergeProps$f(props, {
                    size: "small",
                    color: "warning",
                    class: "mr-2"
                  }), {
                    default: _withCtx$k(() => _cache[6] || (_cache[6] = [
                      _createTextVNode$k(" mdi-eye-off-outline ")
                    ])),
                    _: 2
                  }, 1040)
                ]),
                _: 1
              })) : _createCommentVNode$h("", true),
              _createVNode$k(_component_v_chip, {
                size: "small",
                color: _unref$g(getSourceColor)(__props.proxyGroupData.meta.source),
                variant: "outlined"
              }, {
                default: _withCtx$k(() => [
                  _createTextVNode$k(_toDisplayString$i(__props.proxyGroupData.meta.source), 1)
                ]),
                _: 1
              }, 8, ["color"])
            ])
          ]),
          _createVNode$k(_component_v_card_text, { class: "pt-2 pb-4" }, {
            default: _withCtx$k(() => [
              _createVNode$k(_component_v_row, {
                "no-gutters": "",
                class: "align-center"
              }, {
                default: _withCtx$k(() => [
                  _createVNode$k(_component_v_col, {
                    cols: "3",
                    class: "text-caption text-medium-emphasis"
                  }, {
                    default: _withCtx$k(() => _cache[7] || (_cache[7] = [
                      _createTextVNode$k("类型")
                    ])),
                    _: 1
                  }),
                  _createVNode$k(_component_v_col, { cols: "9" }, {
                    default: _withCtx$k(() => [
                      _createVNode$k(_component_v_chip, {
                        color: _unref$g(getProxyGroupTypeColor)(__props.proxyGroupData.data.type),
                        size: "x-small",
                        label: "",
                        variant: "tonal",
                        class: "font-weight-medium"
                      }, {
                        default: _withCtx$k(() => [
                          _createTextVNode$k(_toDisplayString$i(__props.proxyGroupData.data.type), 1)
                        ]),
                        _: 1
                      }, 8, ["color"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode$k(_component_v_divider),
          _createVNode$k(_component_v_card_actions, null, {
            default: _withCtx$k(() => [
              _createVNode$k(_component_v_icon, {
                color: __props.proxyGroupData.meta.disabled ? "grey" : "success"
              }, {
                default: _withCtx$k(() => [
                  _createTextVNode$k(_toDisplayString$i(__props.proxyGroupData.meta.disabled ? "mdi-close-circle-outline" : "mdi-check-circle-outline"), 1)
                ]),
                _: 1
              }, 8, ["color"]),
              _createVNode$k(_component_v_spacer),
              _createVNode$k(_sfc_main$m, {
                "proxy-group": __props.proxyGroupData,
                onChangeStatus: _cache[0] || (_cache[0] = (disabled) => emit("changeStatus", __props.proxyGroupData.data.name, disabled)),
                onShowYaml: _cache[1] || (_cache[1] = ($event) => emit("showYaml", __props.proxyGroupData.data)),
                onEdit: _cache[2] || (_cache[2] = ($event) => emit("editProxyGroup", __props.proxyGroupData.data.name)),
                onDelete: _cache[3] || (_cache[3] = ($event) => emit("deleteProxyGroup", __props.proxyGroupData.data.name)),
                onDeletePatch: _cache[4] || (_cache[4] = ($event) => emit("deletePatch", __props.proxyGroupData.data.name)),
                onEditVisibility: _cache[5] || (_cache[5] = ($event) => emit("editVisibility", __props.proxyGroupData.data.name))
              }, null, 8, ["proxy-group"])
            ]),
            _: 1
          })
        ]),
        _: 1
      });
    };
  }
});

const ProxyGroupCard = /* @__PURE__ */ _export_sfc(_sfc_main$k, [["__scopeId", "data-v-88bfc397"]]);

const {defineComponent:_defineComponent$j} = await importShared('vue');

const {toDisplayString:_toDisplayString$h,createTextVNode:_createTextVNode$j,resolveComponent:_resolveComponent$j,withCtx:_withCtx$j,createVNode:_createVNode$j,openBlock:_openBlock$j,createBlock:_createBlock$j,createCommentVNode:_createCommentVNode$g,createElementVNode:_createElementVNode$f,withModifiers:_withModifiers$3} = await importShared('vue');

const {ref: ref$d,computed: computed$5,toRaw: toRaw$5} = await importShared('vue');
const _sfc_main$j = /* @__PURE__ */ _defineComponent$j({
  __name: "ProxyGroupsDialog",
  props: {
    initialValue: {
      type: Object,
      default: null
    },
    isAdding: {
      type: Boolean,
      default: true
    },
    proxyProviders: {
      type: Array,
      default: () => []
    },
    customOutbounds: {
      type: Array,
      default: () => []
    },
    api: {
      type: Object,
      required: true
    }
  },
  emits: ["close", "refresh", "show-snackbar", "show-error"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const proxyGroup = ref$d(
      props.initialValue ? structuredClone(toRaw$5(props.initialValue.data)) : { ...defaultProxyGroup }
    );
    const proxyGroupTypes = ref$d(["select", "url-test", "fallback", "load-balance", "smart"]);
    const form = ref$d(null);
    const loading = ref$d(false);
    const proxyProviderNames = computed$5(() => Object.keys(props.proxyProviders));
    const strategyTypes = ref$d(["round-robin", "consistent-hashing", "sticky-sessions"]);
    const smartStrategyTypes = ref$d(["round-robin", "sticky-sessions"]);
    const actions = computed$5(() => [
      "DIRECT",
      "REJECT",
      "REJECT-DROP",
      "PASS",
      "COMPATIBLE",
      ...props.customOutbounds.map((outbound) => outbound)
    ]);
    const urlRules = [
      (v) => {
        return !v || isValidUrl(v) || "请输入一个有效的URL地址";
      }
    ];
    async function saveProxyGroup() {
      if (!form.value) return;
      const { valid } = await form.value.validate();
      if (!valid) return;
      const name = encodeURIComponent(
        props.isAdding ? proxyGroup.value.name : props.initialValue?.data.name || ""
      );
      const action = props.isAdding ? "添加代理组" : "更新代理组";
      loading.value = true;
      try {
        const path = props.isAdding ? "" : `/${name}`;
        const method = props.isAdding ? "post" : "patch";
        const cleanedProxyGroup = JSON.parse(JSON.stringify(toRaw$5(proxyGroup.value)));
        Object.keys(cleanedProxyGroup).forEach((key) => {
          if (cleanedProxyGroup[key] === "") {
            cleanedProxyGroup[key] = null;
          }
        });
        const requestData = props.isAdding ? cleanedProxyGroup : {
          source: props.initialValue?.meta.source,
          proxy_group: cleanedProxyGroup
        };
        const result = await props.api[method](
          `/plugin/ClashRuleProvider/proxy-groups${path}`,
          requestData
        );
        if (!result.success) {
          emit("show-error", action + "失败: " + (result.message || "未知错误"));
          emit("show-snackbar", {
            show: true,
            message: action + "失败",
            color: "error"
          });
          return;
        }
        emit("show-snackbar", {
          show: true,
          message: action + "成功",
          color: "success"
        });
        emit("refresh");
        emit("close");
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", action + "失败: " + (err.message || "未知错误"));
          emit("show-snackbar", {
            show: true,
            message: action + "失败",
            color: "error"
          });
        }
      } finally {
        loading.value = false;
      }
    }
    return (_ctx, _cache) => {
      const _component_v_card_title = _resolveComponent$j("v-card-title");
      const _component_v_text_field = _resolveComponent$j("v-text-field");
      const _component_v_col = _resolveComponent$j("v-col");
      const _component_v_select = _resolveComponent$j("v-select");
      const _component_v_row = _resolveComponent$j("v-row");
      const _component_v_icon = _resolveComponent$j("v-icon");
      const _component_v_switch = _resolveComponent$j("v-switch");
      const _component_v_card_text = _resolveComponent$j("v-card-text");
      const _component_v_alert = _resolveComponent$j("v-alert");
      const _component_v_spacer = _resolveComponent$j("v-spacer");
      const _component_v_btn = _resolveComponent$j("v-btn");
      const _component_v_card_actions = _resolveComponent$j("v-card-actions");
      const _component_v_card = _resolveComponent$j("v-card");
      const _component_v_form = _resolveComponent$j("v-form");
      const _component_v_dialog = _resolveComponent$j("v-dialog");
      return _openBlock$j(), _createBlock$j(_component_v_dialog, { "max-width": "40rem" }, {
        default: _withCtx$j(() => [
          _createVNode$j(_component_v_form, {
            ref_key: "form",
            ref: form,
            onSubmit: _withModifiers$3(saveProxyGroup, ["prevent"])
          }, {
            default: _withCtx$j(() => [
              _createVNode$j(_component_v_card, null, {
                default: _withCtx$j(() => [
                  _createVNode$j(_component_v_card_title, null, {
                    default: _withCtx$j(() => [
                      _createTextVNode$j(_toDisplayString$h(props.isAdding ? "添加代理组" : "编辑代理组"), 1)
                    ]),
                    _: 1
                  }),
                  _createVNode$j(_component_v_card_text, {
                    style: { "overflow-y": "auto" },
                    "max-height": "60rem"
                  }, {
                    default: _withCtx$j(() => [
                      _createVNode$j(_component_v_row, null, {
                        default: _withCtx$j(() => [
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_text_field, {
                                modelValue: proxyGroup.value.name,
                                "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => proxyGroup.value.name = $event),
                                label: "name",
                                required: "",
                                hint: "策略组的名字",
                                rules: [(v) => !!v || "Name不能为空"],
                                class: "mb-4"
                              }, null, 8, ["modelValue", "rules"])
                            ]),
                            _: 1
                          }),
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_select, {
                                modelValue: proxyGroup.value.type,
                                "onUpdate:modelValue": _cache[1] || (_cache[1] = ($event) => proxyGroup.value.type = $event),
                                label: "type",
                                items: proxyGroupTypes.value,
                                required: "",
                                hint: "策略组的类型，smart组需要内核支持",
                                class: "mb-4"
                              }, null, 8, ["modelValue", "items"])
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }),
                      _createVNode$j(_component_v_select, {
                        modelValue: proxyGroup.value.proxies,
                        "onUpdate:modelValue": _cache[2] || (_cache[2] = ($event) => proxyGroup.value.proxies = $event),
                        label: "proxies",
                        items: actions.value,
                        multiple: "",
                        chips: "",
                        clearable: "",
                        hint: "引入出站代理或其他策略组",
                        class: "mb-4"
                      }, null, 8, ["modelValue", "items"]),
                      _createVNode$j(_component_v_select, {
                        modelValue: proxyGroup.value.use,
                        "onUpdate:modelValue": _cache[3] || (_cache[3] = ($event) => proxyGroup.value.use = $event),
                        label: "use",
                        items: proxyProviderNames.value,
                        multiple: "",
                        chips: "",
                        clearable: "",
                        hint: "引入代理集合",
                        class: "mb-4"
                      }, null, 8, ["modelValue", "items"]),
                      _createVNode$j(_component_v_text_field, {
                        modelValue: proxyGroup.value.url,
                        "onUpdate:modelValue": _cache[4] || (_cache[4] = ($event) => proxyGroup.value.url = $event),
                        label: "url",
                        hint: "健康检查测试地址",
                        rules: urlRules,
                        clearable: "",
                        class: "mb-4"
                      }, null, 8, ["modelValue"]),
                      proxyGroup.value.type === "url-test" ? (_openBlock$j(), _createBlock$j(_component_v_text_field, {
                        key: 0,
                        modelValue: proxyGroup.value.tolerance,
                        "onUpdate:modelValue": _cache[5] || (_cache[5] = ($event) => proxyGroup.value.tolerance = $event),
                        modelModifiers: { number: true },
                        label: "tolerance (ms)",
                        variant: "outlined",
                        type: "number",
                        min: "10",
                        hint: "节点切换容差",
                        rules: [(v) => v >= 0 || "容差需不小于0"],
                        class: "mb-4"
                      }, null, 8, ["modelValue", "rules"])) : _createCommentVNode$g("", true),
                      proxyGroup.value.type === "load-balance" ? (_openBlock$j(), _createBlock$j(_component_v_select, {
                        key: 1,
                        modelValue: proxyGroup.value.strategy,
                        "onUpdate:modelValue": _cache[6] || (_cache[6] = ($event) => proxyGroup.value.strategy = $event),
                        label: "strategy",
                        items: strategyTypes.value,
                        hint: "负载均衡策略",
                        class: "mb-4"
                      }, null, 8, ["modelValue", "items"])) : _createCommentVNode$g("", true),
                      proxyGroup.value.type === "smart" ? (_openBlock$j(), _createBlock$j(_component_v_select, {
                        key: 2,
                        modelValue: proxyGroup.value.strategy,
                        "onUpdate:modelValue": _cache[7] || (_cache[7] = ($event) => proxyGroup.value.strategy = $event),
                        label: "strategy",
                        items: smartStrategyTypes.value,
                        hint: "负载均衡策略",
                        class: "mb-4"
                      }, null, 8, ["modelValue", "items"])) : _createCommentVNode$g("", true),
                      proxyGroup.value.type === "smart" ? (_openBlock$j(), _createBlock$j(_component_v_row, { key: 3 }, {
                        default: _withCtx$j(() => [
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_text_field, {
                                modelValue: proxyGroup.value["policy-priority"],
                                "onUpdate:modelValue": _cache[8] || (_cache[8] = ($event) => proxyGroup.value["policy-priority"] = $event),
                                label: "policy-priority",
                                hint: "优先级",
                                clearable: ""
                              }, null, 8, ["modelValue"])
                            ]),
                            _: 1
                          }),
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_text_field, {
                                modelValue: proxyGroup.value["sample-rate"],
                                "onUpdate:modelValue": _cache[9] || (_cache[9] = ($event) => proxyGroup.value["sample-rate"] = $event),
                                modelModifiers: { number: true },
                                label: "sample-rate",
                                type: "number",
                                hint: "数据采集率",
                                clearable: ""
                              }, null, 8, ["modelValue"])
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      })) : _createCommentVNode$g("", true),
                      _createVNode$j(_component_v_row, null, {
                        default: _withCtx$j(() => [
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_text_field, {
                                modelValue: proxyGroup.value.filter,
                                "onUpdate:modelValue": _cache[10] || (_cache[10] = ($event) => proxyGroup.value.filter = $event),
                                label: "filter",
                                hint: "筛选满足关键词或正则表达式的节点",
                                clearable: ""
                              }, null, 8, ["modelValue"])
                            ]),
                            _: 1
                          }),
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_text_field, {
                                modelValue: proxyGroup.value["exclude-filter"],
                                "onUpdate:modelValue": _cache[11] || (_cache[11] = ($event) => proxyGroup.value["exclude-filter"] = $event),
                                label: "exclude-filter",
                                hint: "排除满足关键词或正则表达式的节点",
                                clearable: ""
                              }, null, 8, ["modelValue"])
                            ]),
                            _: 1
                          }),
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_text_field, {
                                modelValue: proxyGroup.value["exclude-type"],
                                "onUpdate:modelValue": _cache[12] || (_cache[12] = ($event) => proxyGroup.value["exclude-type"] = $event),
                                label: "exclude-type",
                                hint: "不支持正则表达式，通过 | 分割",
                                clearable: ""
                              }, null, 8, ["modelValue"])
                            ]),
                            _: 1
                          }),
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_text_field, {
                                modelValue: proxyGroup.value["expected-status"],
                                "onUpdate:modelValue": _cache[13] || (_cache[13] = ($event) => proxyGroup.value["expected-status"] = $event),
                                label: "expected-status",
                                hint: "健康检查时期望的 HTTP 响应状态码",
                                clearable: ""
                              }, null, 8, ["modelValue"])
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }),
                      _createVNode$j(_component_v_row, null, {
                        default: _withCtx$j(() => [
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "12"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_text_field, {
                                modelValue: proxyGroup.value.icon,
                                "onUpdate:modelValue": _cache[14] || (_cache[14] = ($event) => proxyGroup.value.icon = $event),
                                label: "icon",
                                clearable: "",
                                hint: "在 api 返回icon所输入的字符串"
                              }, null, 8, ["modelValue"])
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }),
                      _createVNode$j(_component_v_row, null, {
                        default: _withCtx$j(() => [
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_text_field, {
                                modelValue: proxyGroup.value.interval,
                                "onUpdate:modelValue": _cache[15] || (_cache[15] = ($event) => proxyGroup.value.interval = $event),
                                modelModifiers: { number: true },
                                label: "interval",
                                variant: "outlined",
                                type: "number",
                                min: "0",
                                clearable: "",
                                suffix: "s",
                                hint: "健康检查间隔，如不为 0 则启用定时测试",
                                rules: [(v) => v === null || v === void 0 || v > -1 || "检查间隔需不小于0"]
                              }, {
                                "prepend-inner": _withCtx$j(() => [
                                  _createVNode$j(_component_v_icon, { color: "warning" }, {
                                    default: _withCtx$j(() => _cache[26] || (_cache[26] = [
                                      _createTextVNode$j("mdi-timer")
                                    ])),
                                    _: 1
                                  })
                                ]),
                                _: 1
                              }, 8, ["modelValue", "rules"])
                            ]),
                            _: 1
                          }),
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_text_field, {
                                modelValue: proxyGroup.value.timeout,
                                "onUpdate:modelValue": _cache[16] || (_cache[16] = ($event) => proxyGroup.value.timeout = $event),
                                modelModifiers: { number: true },
                                label: "timeout",
                                variant: "outlined",
                                type: "number",
                                min: "1",
                                hint: "请求的超时时间",
                                suffix: "ms",
                                clearable: "",
                                rules: [(v) => v === null || v === void 0 || v > 0 || "超时时间必须大于0"]
                              }, {
                                "prepend-inner": _withCtx$j(() => [
                                  _createVNode$j(_component_v_icon, { color: "warning" }, {
                                    default: _withCtx$j(() => _cache[27] || (_cache[27] = [
                                      _createTextVNode$j("mdi-timer")
                                    ])),
                                    _: 1
                                  })
                                ]),
                                _: 1
                              }, 8, ["modelValue", "rules"])
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }),
                      _createVNode$j(_component_v_row, null, {
                        default: _withCtx$j(() => [
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_text_field, {
                                modelValue: proxyGroup.value["max-failed-times"],
                                "onUpdate:modelValue": _cache[17] || (_cache[17] = ($event) => proxyGroup.value["max-failed-times"] = $event),
                                modelModifiers: { number: true },
                                label: "max-failed-times",
                                variant: "outlined",
                                type: "number",
                                min: "0",
                                clearable: "",
                                hint: "最大失败次数",
                                rules: [(v) => v >= 0 || "最大失败次数必须大于等于0"]
                              }, null, 8, ["modelValue", "rules"])
                            ]),
                            _: 1
                          }),
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_switch, {
                                modelValue: proxyGroup.value["lazy"],
                                "onUpdate:modelValue": _cache[18] || (_cache[18] = ($event) => proxyGroup.value["lazy"] = $event),
                                label: "lazy",
                                inset: "",
                                hint: "未选择到当前策略组时，不进行测试",
                                "persistent-hint": ""
                              }, null, 8, ["modelValue"])
                            ]),
                            _: 1
                          }),
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_switch, {
                                modelValue: proxyGroup.value["disable-udp"],
                                "onUpdate:modelValue": _cache[19] || (_cache[19] = ($event) => proxyGroup.value["disable-udp"] = $event),
                                label: "disable-udp",
                                inset: "",
                                hint: "禁用该策略组的UDP",
                                "persistent-hint": ""
                              }, null, 8, ["modelValue"])
                            ]),
                            _: 1
                          }),
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_switch, {
                                modelValue: proxyGroup.value.hidden,
                                "onUpdate:modelValue": _cache[20] || (_cache[20] = ($event) => proxyGroup.value.hidden = $event),
                                label: "hidden",
                                inset: "",
                                hint: "在 api 返回hidden状态",
                                "persistent-hint": ""
                              }, null, 8, ["modelValue"])
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }),
                      _createVNode$j(_component_v_row, null, {
                        default: _withCtx$j(() => [
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_switch, {
                                modelValue: proxyGroup.value["include-all"],
                                "onUpdate:modelValue": _cache[21] || (_cache[21] = ($event) => proxyGroup.value["include-all"] = $event),
                                label: "include-all",
                                inset: "",
                                hint: "引入所有出站代理以及代理集合",
                                "persistent-hint": ""
                              }, null, 8, ["modelValue"])
                            ]),
                            _: 1
                          }),
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_switch, {
                                modelValue: proxyGroup.value["include-all-proxies"],
                                "onUpdate:modelValue": _cache[22] || (_cache[22] = ($event) => proxyGroup.value["include-all-proxies"] = $event),
                                label: "include-all-proxies",
                                inset: "",
                                hint: "引入所有出站代理",
                                "persistent-hint": ""
                              }, null, 8, ["modelValue"])
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }),
                      proxyGroup.value.type === "smart" ? (_openBlock$j(), _createBlock$j(_component_v_row, { key: 4 }, {
                        default: _withCtx$j(() => [
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_switch, {
                                modelValue: proxyGroup.value["uselightgbm"],
                                "onUpdate:modelValue": _cache[23] || (_cache[23] = ($event) => proxyGroup.value["uselightgbm"] = $event),
                                label: "uselightgbm",
                                inset: "",
                                hint: "使用LightGBM进行权重预测",
                                "persistent-hint": ""
                              }, null, 8, ["modelValue"])
                            ]),
                            _: 1
                          }),
                          _createVNode$j(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$j(() => [
                              _createVNode$j(_component_v_switch, {
                                modelValue: proxyGroup.value["collectdata"],
                                "onUpdate:modelValue": _cache[24] || (_cache[24] = ($event) => proxyGroup.value["collectdata"] = $event),
                                label: "collectdata",
                                inset: "",
                                hint: "收集数据进行模型训练",
                                "persistent-hint": ""
                              }, null, 8, ["modelValue"])
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      })) : _createCommentVNode$g("", true)
                    ]),
                    _: 1
                  }),
                  _createVNode$j(_component_v_alert, {
                    type: "info",
                    variant: "tonal"
                  }, {
                    default: _withCtx$j(() => _cache[28] || (_cache[28] = [
                      _createTextVNode$j(" 参考"),
                      _createElementVNode$f("a", {
                        href: "https://wiki.metacubex.one/config/proxy-groups/",
                        target: "_blank",
                        style: { "text-decoration": "underline" }
                      }, "Docs", -1)
                    ])),
                    _: 1
                  }),
                  _createVNode$j(_component_v_card_actions, null, {
                    default: _withCtx$j(() => [
                      _createVNode$j(_component_v_spacer),
                      _createVNode$j(_component_v_btn, {
                        color: "secondary",
                        onClick: _cache[25] || (_cache[25] = ($event) => emit("close"))
                      }, {
                        default: _withCtx$j(() => _cache[29] || (_cache[29] = [
                          _createTextVNode$j("取消")
                        ])),
                        _: 1
                      }),
                      _createVNode$j(_component_v_btn, {
                        color: "primary",
                        type: "submit",
                        loading: loading.value
                      }, {
                        default: _withCtx$j(() => _cache[30] || (_cache[30] = [
                          _createTextVNode$j("保存 ")
                        ])),
                        _: 1
                      }, 8, ["loading"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          }, 512)
        ]),
        _: 1
      });
    };
  }
});

const {defineComponent:_defineComponent$i} = await importShared('vue');

const {resolveComponent:_resolveComponent$i,createVNode:_createVNode$i,withCtx:_withCtx$i,createElementVNode:_createElementVNode$e,renderList:_renderList$7,Fragment:_Fragment$7,openBlock:_openBlock$i,createElementBlock:_createElementBlock$8,createBlock:_createBlock$i,unref:_unref$f,toDisplayString:_toDisplayString$g,createTextVNode:_createTextVNode$i,mergeProps:_mergeProps$e,createCommentVNode:_createCommentVNode$f} = await importShared('vue');

const _hoisted_1$d = { class: "mb-2 position-relative" };
const _hoisted_2$a = { class: "pa-4" };
const _hoisted_3$a = { class: "d-none d-sm-flex clash-data-table" };
const _hoisted_4$9 = { class: "d-sm-none" };
const _hoisted_5$6 = {
  class: "pa-4",
  style: { "min-height": "4rem" }
};
const {computed: computed$4,ref: ref$c} = await importShared('vue');
const _sfc_main$i = /* @__PURE__ */ _defineComponent$i({
  __name: "ProxyGroupsTab",
  props: {
    proxyGroups: {},
    proxyProviders: {},
    customOutbounds: {},
    api: {}
  },
  emits: ["refresh", "show-snackbar", "show-error", "show-yaml", "copy-to-clipboard", "edit-visibility"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const searchProxyGroups = ref$c("");
    const pageProxyGroup = ref$c(1);
    const itemsPerPageProxyGroup = ref$c(10);
    const loading = ref$c(false);
    const proxyGroupDialogVisible = ref$c(false);
    const editingProxyGroupName = ref$c(null);
    const currentProxyGroup = ref$c(null);
    const filteredProxyGroups = computed$4(() => {
      if (!searchProxyGroups.value) return props.proxyGroups;
      const keyword = searchProxyGroups.value.toLowerCase();
      return props.proxyGroups.filter(
        (item) => Object.values(item).some((val) => String(val).toLowerCase().includes(keyword))
      );
    });
    const paginatedProxyGroups = computed$4(() => {
      const start = (pageProxyGroup.value - 1) * itemsPerPageProxyGroup.value;
      const end = start + itemsPerPageProxyGroup.value;
      return filteredProxyGroups.value.slice(start, end);
    });
    const pageCountProxyGroups = computed$4(() => {
      if (itemsPerPageProxyGroup.value === -1) {
        return 1;
      }
      return Math.ceil(filteredProxyGroups.value.length / itemsPerPageProxyGroup.value);
    });
    function openAddProxyGroupDialog() {
      editingProxyGroupName.value = null;
      currentProxyGroup.value = null;
      proxyGroupDialogVisible.value = true;
    }
    function editProxyGroup(name) {
      const proxyGroupData = props.proxyGroups.find((p) => p.data.name === name);
      if (proxyGroupData) {
        editingProxyGroupName.value = name;
        currentProxyGroup.value = { ...proxyGroupData };
        proxyGroupDialogVisible.value = true;
      }
    }
    async function deleteProxyGroup(name) {
      loading.value = true;
      try {
        const n = encodeURIComponent(name);
        await props.api.delete(`/plugin/ClashRuleProvider/proxy-groups/${n}`);
        emit("refresh", ["proxy-groups", "clash-outbounds"]);
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", err.message || "删除规则失败");
        }
      } finally {
        loading.value = false;
      }
    }
    async function deletePatch(name) {
      loading.value = true;
      try {
        const n = encodeURIComponent(name);
        await props.api.delete(`/plugin/ClashRuleProvider/proxy-groups/${n}/patch`);
        emit("refresh", ["proxy-groups", "clash-outbounds"]);
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", err.message || "删除补丁失败");
        }
      } finally {
        loading.value = false;
      }
    }
    async function handleStatusChange(name, disabled) {
      loading.value = true;
      try {
        const group = props.proxyGroups.find((g) => g.data.name === name);
        if (!group) {
          emit("show-error", "Proxy group not found");
          return;
        }
        const n = encodeURIComponent(name);
        const newMeta = { ...group.meta, disabled };
        await props.api.patch(`/plugin/ClashRuleProvider/proxy-groups/${n}/meta`, newMeta);
        emit("refresh", ["proxy-groups", "clash-outbounds"]);
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", err.message || "更新代理组状态失败");
        }
      } finally {
        loading.value = false;
      }
    }
    function editVisibility(name) {
      const group = props.proxyGroups.find((g) => g.data.name === name);
      if (!group) {
        emit("show-error", "Proxy group not found");
        return;
      }
      const n = encodeURIComponent(name);
      emit(
        "edit-visibility",
        group.meta,
        `/plugin/ClashRuleProvider/proxy-groups/${n}/meta`,
        "proxy-groups"
      );
    }
    function closeProxyGroupsDialog() {
      currentProxyGroup.value = null;
      proxyGroupDialogVisible.value = false;
    }
    return (_ctx, _cache) => {
      const _component_v_progress_circular = _resolveComponent$i("v-progress-circular");
      const _component_v_overlay = _resolveComponent$i("v-overlay");
      const _component_v_text_field = _resolveComponent$i("v-text-field");
      const _component_v_col = _resolveComponent$i("v-col");
      const _component_v_btn = _resolveComponent$i("v-btn");
      const _component_v_btn_group = _resolveComponent$i("v-btn-group");
      const _component_v_row = _resolveComponent$i("v-row");
      const _component_v_pagination = _resolveComponent$i("v-pagination");
      const _component_v_list_item_title = _resolveComponent$i("v-list-item-title");
      const _component_v_list_item = _resolveComponent$i("v-list-item");
      const _component_v_list = _resolveComponent$i("v-list");
      const _component_v_menu = _resolveComponent$i("v-menu");
      const _component_v_divider = _resolveComponent$i("v-divider");
      return _openBlock$i(), _createElementBlock$8("div", _hoisted_1$d, [
        _createVNode$i(_component_v_overlay, {
          modelValue: loading.value,
          "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => loading.value = $event),
          contained: "",
          class: "align-center justify-center"
        }, {
          default: _withCtx$i(() => [
            _createVNode$i(_component_v_progress_circular, {
              indeterminate: "",
              color: "primary"
            })
          ]),
          _: 1
        }, 8, ["modelValue"]),
        _createElementVNode$e("div", _hoisted_2$a, [
          _createVNode$i(_component_v_row, {
            align: "center",
            "no-gutters": ""
          }, {
            default: _withCtx$i(() => [
              _createVNode$i(_component_v_col, {
                cols: "10",
                sm: "6",
                class: "d-flex justify-start"
              }, {
                default: _withCtx$i(() => [
                  _createVNode$i(_component_v_text_field, {
                    modelValue: searchProxyGroups.value,
                    "onUpdate:modelValue": _cache[1] || (_cache[1] = ($event) => searchProxyGroups.value = $event),
                    label: "搜索代理组",
                    clearable: "",
                    density: "compact",
                    variant: "solo-filled",
                    "hide-details": "",
                    class: "search-field",
                    "prepend-inner-icon": "mdi-magnify",
                    flat: "",
                    rounded: "pill",
                    "single-line": "",
                    disabled: loading.value
                  }, null, 8, ["modelValue", "disabled"])
                ]),
                _: 1
              }),
              _createVNode$i(_component_v_col, {
                cols: "2",
                sm: "6",
                class: "d-flex justify-end"
              }, {
                default: _withCtx$i(() => [
                  _createVNode$i(_component_v_btn_group, {
                    variant: "outlined",
                    rounded: ""
                  }, {
                    default: _withCtx$i(() => [
                      _createVNode$i(_component_v_btn, {
                        icon: "mdi-plus",
                        disabled: loading.value,
                        onClick: openAddProxyGroupDialog
                      }, null, 8, ["disabled"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _createElementVNode$e("div", _hoisted_3$a, [
          _createVNode$i(_sfc_main$l, {
            "items-per-page": itemsPerPageProxyGroup.value,
            page: pageProxyGroup.value,
            "proxy-groups": _ctx.proxyGroups,
            search: searchProxyGroups.value,
            onCopyToClipboard: _cache[2] || (_cache[2] = (t) => emit("copy-to-clipboard", t)),
            onShowYaml: _cache[3] || (_cache[3] = (o) => emit("show-yaml", o)),
            onEditProxyGroup: editProxyGroup,
            onDeleteProxyGroup: deleteProxyGroup,
            onDeletePatch: deletePatch,
            onChangeStatus: handleStatusChange,
            onEditVisibility: editVisibility
          }, null, 8, ["items-per-page", "page", "proxy-groups", "search"])
        ]),
        _createElementVNode$e("div", _hoisted_4$9, [
          _createVNode$i(_component_v_row, null, {
            default: _withCtx$i(() => [
              (_openBlock$i(true), _createElementBlock$8(_Fragment$7, null, _renderList$7(paginatedProxyGroups.value, (item) => {
                return _openBlock$i(), _createBlock$i(_component_v_col, {
                  key: item.data.name,
                  cols: "12"
                }, {
                  default: _withCtx$i(() => [
                    _createVNode$i(ProxyGroupCard, {
                      "proxy-group-data": item,
                      onEditProxyGroup: editProxyGroup,
                      onDeleteProxyGroup: deleteProxyGroup,
                      onDeletePatch: deletePatch,
                      onShowYaml: _cache[4] || (_cache[4] = (o) => emit("show-yaml", o)),
                      onChangeStatus: handleStatusChange,
                      onEditVisibility: editVisibility
                    }, null, 8, ["proxy-group-data"])
                  ]),
                  _: 2
                }, 1024);
              }), 128))
            ]),
            _: 1
          })
        ]),
        _createElementVNode$e("div", _hoisted_5$6, [
          _createVNode$i(_component_v_row, {
            align: "center",
            "no-gutters": ""
          }, {
            default: _withCtx$i(() => [
              _createVNode$i(_component_v_col, {
                cols: "2",
                md: "1"
              }),
              _createVNode$i(_component_v_col, {
                cols: "8",
                md: "10",
                class: "d-flex justify-center"
              }, {
                default: _withCtx$i(() => [
                  _createVNode$i(_component_v_pagination, {
                    modelValue: pageProxyGroup.value,
                    "onUpdate:modelValue": _cache[5] || (_cache[5] = ($event) => pageProxyGroup.value = $event),
                    length: pageCountProxyGroups.value,
                    "total-visible": "5",
                    class: "d-none d-sm-flex my-0",
                    rounded: "circle",
                    disabled: loading.value
                  }, null, 8, ["modelValue", "length", "disabled"]),
                  _createVNode$i(_component_v_pagination, {
                    modelValue: pageProxyGroup.value,
                    "onUpdate:modelValue": _cache[6] || (_cache[6] = ($event) => pageProxyGroup.value = $event),
                    length: pageCountProxyGroups.value,
                    "total-visible": "0",
                    class: "d-sm-none my-0",
                    rounded: "circle",
                    disabled: loading.value
                  }, null, 8, ["modelValue", "length", "disabled"])
                ]),
                _: 1
              }),
              _createVNode$i(_component_v_col, {
                cols: "2",
                md: "1",
                class: "d-flex justify-end"
              }, {
                default: _withCtx$i(() => [
                  _createVNode$i(_component_v_menu, null, {
                    activator: _withCtx$i(({ props: props2 }) => [
                      _createVNode$i(_component_v_btn, _mergeProps$e(props2, {
                        icon: "",
                        rounded: "circle",
                        variant: "tonal",
                        disabled: loading.value
                      }), {
                        default: _withCtx$i(() => [
                          _createTextVNode$i(_toDisplayString$g(_unref$f(pageTitle)(itemsPerPageProxyGroup.value)), 1)
                        ]),
                        _: 2
                      }, 1040, ["disabled"])
                    ]),
                    default: _withCtx$i(() => [
                      _createVNode$i(_component_v_list, null, {
                        default: _withCtx$i(() => [
                          (_openBlock$i(true), _createElementBlock$8(_Fragment$7, null, _renderList$7(_unref$f(itemsPerPageOptions), (item, index) => {
                            return _openBlock$i(), _createBlock$i(_component_v_list_item, {
                              key: index,
                              value: item.value,
                              onClick: ($event) => itemsPerPageProxyGroup.value = item.value
                            }, {
                              default: _withCtx$i(() => [
                                _createVNode$i(_component_v_list_item_title, null, {
                                  default: _withCtx$i(() => [
                                    _createTextVNode$i(_toDisplayString$g(item.title), 1)
                                  ]),
                                  _: 2
                                }, 1024)
                              ]),
                              _: 2
                            }, 1032, ["value", "onClick"]);
                          }), 128))
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _createVNode$i(_component_v_divider),
        proxyGroupDialogVisible.value ? (_openBlock$i(), _createBlock$i(_sfc_main$j, {
          key: 0,
          modelValue: proxyGroupDialogVisible.value,
          "onUpdate:modelValue": _cache[7] || (_cache[7] = ($event) => proxyGroupDialogVisible.value = $event),
          "initial-value": currentProxyGroup.value,
          "is-adding": editingProxyGroupName.value === null,
          "proxy-providers": _ctx.proxyProviders,
          "custom-outbounds": _ctx.customOutbounds,
          api: _ctx.api,
          onClose: closeProxyGroupsDialog,
          onRefresh: _cache[8] || (_cache[8] = ($event) => emit("refresh", ["clash-outbounds", "proxy-groups"])),
          onShowSnackbar: _cache[9] || (_cache[9] = (val) => emit("show-snackbar", val)),
          onShowError: _cache[10] || (_cache[10] = (msg) => emit("show-error", msg))
        }, null, 8, ["modelValue", "initial-value", "is-adding", "proxy-providers", "custom-outbounds", "api"])) : _createCommentVNode$f("", true)
      ]);
    };
  }
});

const {defineComponent:_defineComponent$h} = await importShared('vue');

const {createTextVNode:_createTextVNode$h,resolveComponent:_resolveComponent$h,withCtx:_withCtx$h,createVNode:_createVNode$h,mergeProps:_mergeProps$d,unref:_unref$e,toDisplayString:_toDisplayString$f,openBlock:_openBlock$h,createBlock:_createBlock$h,createCommentVNode:_createCommentVNode$e} = await importShared('vue');
const _sfc_main$h = /* @__PURE__ */ _defineComponent$h({
  __name: "ProxyActionMenu",
  props: {
    proxy: {
      type: Object,
      required: true
    }
  },
  emits: ["showYaml", "edit", "delete", "deletePatch", "changeStatus", "copyToClipboard", "editVisibility"],
  setup(__props, { emit: __emit }) {
    const emit = __emit;
    return (_ctx, _cache) => {
      const _component_v_icon = _resolveComponent$h("v-icon");
      const _component_v_btn = _resolveComponent$h("v-btn");
      const _component_v_list_item_title = _resolveComponent$h("v-list-item-title");
      const _component_v_list_item = _resolveComponent$h("v-list-item");
      const _component_v_list = _resolveComponent$h("v-list");
      const _component_v_menu = _resolveComponent$h("v-menu");
      return _openBlock$h(), _createBlock$h(_component_v_menu, { "min-width": "120" }, {
        activator: _withCtx$h(({ props }) => [
          _createVNode$h(_component_v_btn, _mergeProps$d({
            color: "secondary",
            icon: "",
            size: "small",
            variant: "text"
          }, props), {
            default: _withCtx$h(() => [
              _createVNode$h(_component_v_icon, null, {
                default: _withCtx$h(() => _cache[7] || (_cache[7] = [
                  _createTextVNode$h("mdi-dots-vertical")
                ])),
                _: 1
              })
            ]),
            _: 2
          }, 1040)
        ]),
        default: _withCtx$h(() => [
          _createVNode$h(_component_v_list, { density: "compact" }, {
            default: _withCtx$h(() => [
              _unref$e(isManual)(__props.proxy.meta.source) ? (_openBlock$h(), _createBlock$h(_component_v_list_item, {
                key: 0,
                onClick: _cache[0] || (_cache[0] = ($event) => emit("changeStatus", !__props.proxy.meta.disabled))
              }, {
                prepend: _withCtx$h(() => [
                  _createVNode$h(_component_v_icon, {
                    size: "small",
                    color: __props.proxy.meta.disabled ? "success" : "grey"
                  }, {
                    default: _withCtx$h(() => [
                      _createTextVNode$h(_toDisplayString$f(__props.proxy.meta.disabled ? "mdi-play-circle-outline" : "mdi-stop-circle-outline"), 1)
                    ]),
                    _: 1
                  }, 8, ["color"])
                ]),
                default: _withCtx$h(() => [
                  _createVNode$h(_component_v_list_item_title, null, {
                    default: _withCtx$h(() => [
                      _createTextVNode$h(_toDisplayString$f(__props.proxy.meta.disabled ? "启用" : "禁用"), 1)
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })) : _createCommentVNode$e("", true),
              _createVNode$h(_component_v_list_item, {
                onClick: _cache[1] || (_cache[1] = ($event) => emit("showYaml"))
              }, {
                prepend: _withCtx$h(() => [
                  _createVNode$h(_component_v_icon, {
                    size: "small",
                    color: "info"
                  }, {
                    default: _withCtx$h(() => _cache[8] || (_cache[8] = [
                      _createTextVNode$h("mdi-code-json")
                    ])),
                    _: 1
                  })
                ]),
                default: _withCtx$h(() => [
                  _createVNode$h(_component_v_list_item_title, null, {
                    default: _withCtx$h(() => _cache[9] || (_cache[9] = [
                      _createTextVNode$h("查看")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              }),
              _createVNode$h(_component_v_list_item, {
                onClick: _cache[2] || (_cache[2] = ($event) => emit("edit"))
              }, {
                prepend: _withCtx$h(() => [
                  _createVNode$h(_component_v_icon, {
                    size: "small",
                    color: "primary"
                  }, {
                    default: _withCtx$h(() => _cache[10] || (_cache[10] = [
                      _createTextVNode$h("mdi-file-edit-outline")
                    ])),
                    _: 1
                  })
                ]),
                default: _withCtx$h(() => [
                  _createVNode$h(_component_v_list_item_title, null, {
                    default: _withCtx$h(() => _cache[11] || (_cache[11] = [
                      _createTextVNode$h("编辑")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              }),
              _unref$e(isManual)(__props.proxy.meta.source) ? (_openBlock$h(), _createBlock$h(_component_v_list_item, {
                key: 1,
                onClick: _cache[3] || (_cache[3] = ($event) => emit("editVisibility"))
              }, {
                prepend: _withCtx$h(() => [
                  _createVNode$h(_component_v_icon, {
                    size: "small",
                    color: "warning"
                  }, {
                    default: _withCtx$h(() => _cache[12] || (_cache[12] = [
                      _createTextVNode$h("mdi-eye-off-outline")
                    ])),
                    _: 1
                  })
                ]),
                default: _withCtx$h(() => [
                  _createVNode$h(_component_v_list_item_title, null, {
                    default: _withCtx$h(() => _cache[13] || (_cache[13] = [
                      _createTextVNode$h("隐藏")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              })) : _createCommentVNode$e("", true),
              __props.proxy.v2ray_link ? (_openBlock$h(), _createBlock$h(_component_v_list_item, {
                key: 2,
                onClick: _cache[4] || (_cache[4] = ($event) => emit("copyToClipboard", __props.proxy.v2ray_link))
              }, {
                prepend: _withCtx$h(() => [
                  _createVNode$h(_component_v_icon, {
                    size: "small",
                    color: "secondary"
                  }, {
                    default: _withCtx$h(() => _cache[14] || (_cache[14] = [
                      _createTextVNode$h("mdi-link")
                    ])),
                    _: 1
                  })
                ]),
                default: _withCtx$h(() => [
                  _createVNode$h(_component_v_list_item_title, null, {
                    default: _withCtx$h(() => _cache[15] || (_cache[15] = [
                      _createTextVNode$h("复制链接")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              })) : _createCommentVNode$e("", true),
              __props.proxy.meta.patched ? (_openBlock$h(), _createBlock$h(_component_v_list_item, {
                key: 3,
                onClick: _cache[5] || (_cache[5] = ($event) => emit("deletePatch"))
              }, {
                prepend: _withCtx$h(() => [
                  _createVNode$h(_component_v_icon, {
                    size: "small",
                    color: "error"
                  }, {
                    default: _withCtx$h(() => _cache[16] || (_cache[16] = [
                      _createTextVNode$h("mdi-close-box-outline")
                    ])),
                    _: 1
                  })
                ]),
                default: _withCtx$h(() => [
                  _createVNode$h(_component_v_list_item_title, null, {
                    default: _withCtx$h(() => _cache[17] || (_cache[17] = [
                      _createTextVNode$h("删除补丁")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              })) : _createCommentVNode$e("", true),
              _createVNode$h(_component_v_list_item, {
                disabled: !(_unref$e(isManual)(__props.proxy.meta.source) || _unref$e(isInvalid)(__props.proxy.meta.source)),
                onClick: _cache[6] || (_cache[6] = ($event) => emit("delete"))
              }, {
                prepend: _withCtx$h(() => [
                  _createVNode$h(_component_v_icon, {
                    size: "small",
                    color: "error"
                  }, {
                    default: _withCtx$h(() => _cache[18] || (_cache[18] = [
                      _createTextVNode$h("mdi-trash-can-outline")
                    ])),
                    _: 1
                  })
                ]),
                default: _withCtx$h(() => [
                  _createVNode$h(_component_v_list_item_title, null, {
                    default: _withCtx$h(() => _cache[19] || (_cache[19] = [
                      _createTextVNode$h("删除")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              }, 8, ["disabled"])
            ]),
            _: 1
          })
        ]),
        _: 1
      });
    };
  }
});

const {defineComponent:_defineComponent$g} = await importShared('vue');

const {unref:_unref$d,toDisplayString:_toDisplayString$e,createTextVNode:_createTextVNode$g,resolveComponent:_resolveComponent$g,withCtx:_withCtx$g,createVNode:_createVNode$g,openBlock:_openBlock$g,createBlock:_createBlock$g,createCommentVNode:_createCommentVNode$d,createElementVNode:_createElementVNode$d,mergeProps:_mergeProps$c} = await importShared('vue');

const _hoisted_1$c = { class: "d-flex align-center" };
const {ref: ref$b} = await importShared('vue');
const _sfc_main$g = /* @__PURE__ */ _defineComponent$g({
  __name: "ProxiesTable",
  props: {
    proxies: {
      type: Array,
      required: true
    },
    page: {
      type: Number,
      required: true
    },
    itemsPerPage: {
      type: Number,
      required: true
    },
    search: String
  },
  emits: ["copyToClipboard", "showYaml", "editProxy", "deleteProxy", "deletePatch", "changeStatus", "editVisibility"],
  setup(__props, { emit: __emit }) {
    const emit = __emit;
    const headers = ref$b([
      { title: "名称", key: "name", sortable: true },
      { title: "类型", key: "type", sortable: false },
      { title: "服务器", key: "server", sortable: false },
      { title: "端口", key: "port", sortable: false },
      { title: "来源", key: "source", sortable: false },
      { title: "", key: "status", sortable: false, width: "1.5rem" },
      { title: "", key: "actions", sortable: false, width: "1rem" }
    ]);
    return (_ctx, _cache) => {
      const _component_v_chip = _resolveComponent$g("v-chip");
      const _component_v_icon = _resolveComponent$g("v-icon");
      const _component_v_btn = _resolveComponent$g("v-btn");
      const _component_v_tooltip = _resolveComponent$g("v-tooltip");
      const _component_v_data_table = _resolveComponent$g("v-data-table");
      return _openBlock$g(), _createBlock$g(_component_v_data_table, {
        class: "px-4",
        headers: headers.value,
        search: __props.search,
        items: __props.proxies,
        page: __props.page,
        "items-per-page": __props.itemsPerPage,
        "items-per-page-options": _unref$d(itemsPerPageOptions),
        "item-key": "name",
        density: "compact",
        "hide-default-footer": "",
        "fixed-header": ""
      }, {
        "item.name": _withCtx$g(({ item }) => [
          _createVNode$g(_component_v_chip, {
            size: "small",
            pill: "",
            color: "secondary"
          }, {
            default: _withCtx$g(() => [
              _createTextVNode$g(_toDisplayString$e(item.data.name), 1)
            ]),
            _: 2
          }, 1024),
          item.v2ray_link ? (_openBlock$g(), _createBlock$g(_component_v_btn, {
            key: 0,
            icon: "",
            size: "small",
            color: "secondary",
            variant: "text",
            onClick: ($event) => emit("copyToClipboard", item.v2ray_link)
          }, {
            default: _withCtx$g(() => [
              _createVNode$g(_component_v_icon, null, {
                default: _withCtx$g(() => _cache[1] || (_cache[1] = [
                  _createTextVNode$g("mdi-link")
                ])),
                _: 1
              })
            ]),
            _: 2
          }, 1032, ["onClick"])) : _createCommentVNode$d("", true)
        ]),
        "item.type": _withCtx$g(({ item }) => [
          _createVNode$g(_component_v_chip, {
            color: _unref$d(getProxyColor)(item.data.type),
            size: "small",
            label: "",
            variant: "tonal"
          }, {
            default: _withCtx$g(() => [
              _createTextVNode$g(_toDisplayString$e(item.data.type), 1)
            ]),
            _: 2
          }, 1032, ["color"])
        ]),
        "item.server": _withCtx$g(({ item }) => [
          _createElementVNode$d("small", null, _toDisplayString$e(item.data.server), 1)
        ]),
        "item.port": _withCtx$g(({ item }) => [
          _createVNode$g(_component_v_chip, {
            size: "x-small",
            label: "",
            variant: "tonal",
            color: "primary"
          }, {
            default: _withCtx$g(() => [
              _createTextVNode$g(_toDisplayString$e(item.data.port), 1)
            ]),
            _: 2
          }, 1024)
        ]),
        "item.source": _withCtx$g(({ item }) => [
          _createVNode$g(_component_v_chip, {
            color: _unref$d(getSourceColor)(item.meta.source),
            size: "small",
            variant: "outlined"
          }, {
            default: _withCtx$g(() => [
              _createTextVNode$g(_toDisplayString$e(item.meta.source), 1)
            ]),
            _: 2
          }, 1032, ["color"])
        ]),
        "item.status": _withCtx$g(({ item }) => [
          _createElementVNode$d("div", _hoisted_1$c, [
            _createVNode$g(_component_v_icon, {
              color: item.meta.disabled ? "grey" : "success",
              class: "mr-1"
            }, {
              default: _withCtx$g(() => [
                _createTextVNode$g(_toDisplayString$e(item.meta.disabled ? "mdi-close-circle-outline" : "mdi-check-circle-outline"), 1)
              ]),
              _: 2
            }, 1032, ["color"]),
            item.meta.invisible_to && item.meta.invisible_to.length > 0 ? (_openBlock$g(), _createBlock$g(_component_v_tooltip, {
              key: 0,
              text: "已配置可见性限制",
              location: "top"
            }, {
              activator: _withCtx$g(({ props }) => [
                _createVNode$g(_component_v_icon, _mergeProps$c(props, {
                  size: "small",
                  color: "warning"
                }), {
                  default: _withCtx$g(() => _cache[2] || (_cache[2] = [
                    _createTextVNode$g(" mdi-eye-off-outline ")
                  ])),
                  _: 2
                }, 1040)
              ]),
              _: 1
            })) : _createCommentVNode$d("", true),
            item.meta.patched ? (_openBlock$g(), _createBlock$g(_component_v_tooltip, {
              key: 1,
              text: "已应用补丁",
              location: "top"
            }, {
              activator: _withCtx$g(({ props }) => [
                _createVNode$g(_component_v_icon, _mergeProps$c(props, {
                  size: "small",
                  color: "info"
                }), {
                  default: _withCtx$g(() => _cache[3] || (_cache[3] = [
                    _createTextVNode$g(" mdi-auto-fix ")
                  ])),
                  _: 2
                }, 1040)
              ]),
              _: 1
            })) : _createCommentVNode$d("", true)
          ])
        ]),
        "item.actions": _withCtx$g(({ item }) => [
          _createVNode$g(_sfc_main$h, {
            proxy: item,
            onChangeStatus: (disabled) => emit("changeStatus", item.data.name, disabled),
            onShowYaml: ($event) => emit("showYaml", item.data),
            onEdit: ($event) => emit("editProxy", item),
            onDelete: ($event) => emit("deleteProxy", item.data.name),
            onDeletePatch: ($event) => emit("deletePatch", item.data.name),
            onCopyToClipboard: _cache[0] || (_cache[0] = (text) => emit("copyToClipboard", text)),
            onEditVisibility: ($event) => emit("editVisibility", item.data.name)
          }, null, 8, ["proxy", "onChangeStatus", "onShowYaml", "onEdit", "onDelete", "onDeletePatch", "onEditVisibility"])
        ]),
        _: 1
      }, 8, ["headers", "search", "items", "page", "items-per-page", "items-per-page-options"]);
    };
  }
});

const {defineComponent:_defineComponent$f} = await importShared('vue');

const {toDisplayString:_toDisplayString$d,createElementVNode:_createElementVNode$c,createTextVNode:_createTextVNode$f,resolveComponent:_resolveComponent$f,mergeProps:_mergeProps$b,withCtx:_withCtx$f,createVNode:_createVNode$f,openBlock:_openBlock$f,createBlock:_createBlock$f,createCommentVNode:_createCommentVNode$c,unref:_unref$c} = await importShared('vue');

const _hoisted_1$b = { class: "d-flex justify-space-between align-center px-4 pt-3" };
const _hoisted_2$9 = ["title"];
const _hoisted_3$9 = { class: "d-flex align-center" };
const _sfc_main$f = /* @__PURE__ */ _defineComponent$f({
  __name: "ProxyCard",
  props: {
    proxyData: {
      type: Object,
      required: true
    }
  },
  emits: ["copyToClipboard", "showYaml", "editProxy", "deleteProxy", "deletePatch", "changeStatus", "editVisibility"],
  setup(__props, { emit: __emit }) {
    const emit = __emit;
    return (_ctx, _cache) => {
      const _component_v_icon = _resolveComponent$f("v-icon");
      const _component_v_tooltip = _resolveComponent$f("v-tooltip");
      const _component_v_chip = _resolveComponent$f("v-chip");
      const _component_v_col = _resolveComponent$f("v-col");
      const _component_v_row = _resolveComponent$f("v-row");
      const _component_v_card_text = _resolveComponent$f("v-card-text");
      const _component_v_divider = _resolveComponent$f("v-divider");
      const _component_v_spacer = _resolveComponent$f("v-spacer");
      const _component_v_card_actions = _resolveComponent$f("v-card-actions");
      const _component_v_card = _resolveComponent$f("v-card");
      return _openBlock$f(), _createBlock$f(_component_v_card, {
        rounded: "lg",
        elevation: "2",
        class: "proxy-card h-100 transition-swing",
        variant: "tonal"
      }, {
        default: _withCtx$f(() => [
          _createElementVNode$c("div", _hoisted_1$b, [
            _createElementVNode$c("span", {
              class: "font-weight-bold text-truncate",
              title: __props.proxyData.data.name
            }, _toDisplayString$d(__props.proxyData.data.name), 9, _hoisted_2$9),
            _createElementVNode$c("div", _hoisted_3$9, [
              __props.proxyData.meta.invisible_to && __props.proxyData.meta.invisible_to.length > 0 ? (_openBlock$f(), _createBlock$f(_component_v_tooltip, {
                key: 0,
                text: "已配置可见性限制",
                location: "top"
              }, {
                activator: _withCtx$f(({ props }) => [
                  _createVNode$f(_component_v_icon, _mergeProps$b(props, {
                    size: "small",
                    color: "warning",
                    class: "mr-2"
                  }), {
                    default: _withCtx$f(() => _cache[7] || (_cache[7] = [
                      _createTextVNode$f(" mdi-eye-off-outline ")
                    ])),
                    _: 2
                  }, 1040)
                ]),
                _: 1
              })) : _createCommentVNode$c("", true),
              _createVNode$f(_component_v_chip, {
                size: "small",
                color: _unref$c(getSourceColor)(__props.proxyData.meta.source),
                variant: "outlined"
              }, {
                default: _withCtx$f(() => [
                  _createTextVNode$f(_toDisplayString$d(__props.proxyData.meta.source), 1)
                ]),
                _: 1
              }, 8, ["color"])
            ])
          ]),
          _createVNode$f(_component_v_card_text, { class: "pt-2 pb-4" }, {
            default: _withCtx$f(() => [
              _createVNode$f(_component_v_row, {
                "no-gutters": "",
                class: "mb-2 align-center"
              }, {
                default: _withCtx$f(() => [
                  _createVNode$f(_component_v_col, {
                    cols: "3",
                    class: "text-caption text-medium-emphasis"
                  }, {
                    default: _withCtx$f(() => _cache[8] || (_cache[8] = [
                      _createTextVNode$f("类型")
                    ])),
                    _: 1
                  }),
                  _createVNode$f(_component_v_col, { cols: "9" }, {
                    default: _withCtx$f(() => [
                      _createVNode$f(_component_v_chip, {
                        color: _unref$c(getProxyColor)(__props.proxyData.data.type),
                        size: "x-small",
                        label: "",
                        variant: "tonal",
                        class: "font-weight-medium"
                      }, {
                        default: _withCtx$f(() => [
                          _createTextVNode$f(_toDisplayString$d(__props.proxyData.data.type), 1)
                        ]),
                        _: 1
                      }, 8, ["color"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode$f(_component_v_divider),
          _createVNode$f(_component_v_card_actions, null, {
            default: _withCtx$f(() => [
              _createVNode$f(_component_v_icon, {
                color: __props.proxyData.meta.disabled ? "grey" : "success"
              }, {
                default: _withCtx$f(() => [
                  _createTextVNode$f(_toDisplayString$d(__props.proxyData.meta.disabled ? "mdi-close-circle-outline" : "mdi-check-circle-outline"), 1)
                ]),
                _: 1
              }, 8, ["color"]),
              _createVNode$f(_component_v_spacer),
              _createVNode$f(_sfc_main$h, {
                proxy: __props.proxyData,
                onChangeStatus: _cache[0] || (_cache[0] = (disabled) => emit("changeStatus", __props.proxyData.data.name, disabled)),
                onShowYaml: _cache[1] || (_cache[1] = ($event) => emit("showYaml", __props.proxyData.data)),
                onEdit: _cache[2] || (_cache[2] = ($event) => emit("editProxy", __props.proxyData)),
                onDelete: _cache[3] || (_cache[3] = ($event) => emit("deleteProxy", __props.proxyData.data.name)),
                onDeletePatch: _cache[4] || (_cache[4] = ($event) => emit("deletePatch", __props.proxyData.data.name)),
                onCopyToClipboard: _cache[5] || (_cache[5] = (text) => emit("copyToClipboard", text)),
                onEditVisibility: _cache[6] || (_cache[6] = ($event) => emit("editVisibility", __props.proxyData.data.name))
              }, null, 8, ["proxy"])
            ]),
            _: 1
          })
        ]),
        _: 1
      });
    };
  }
});

const ProxyCard = /* @__PURE__ */ _export_sfc(_sfc_main$f, [["__scopeId", "data-v-e80a10d3"]]);

const {defineComponent:_defineComponent$e} = await importShared('vue');

const {createTextVNode:_createTextVNode$e,resolveComponent:_resolveComponent$e,withCtx:_withCtx$e,createVNode:_createVNode$e,openBlock:_openBlock$e,createBlock:_createBlock$e,createCommentVNode:_createCommentVNode$b,createElementBlock:_createElementBlock$7,withModifiers:_withModifiers$2,createElementVNode:_createElementVNode$b} = await importShared('vue');

const _hoisted_1$a = { key: 0 };
const _hoisted_2$8 = {
  key: 0,
  class: "mt-2"
};
const _hoisted_3$8 = {
  key: 0,
  class: "mt-2"
};
const _hoisted_4$8 = {
  key: 0,
  class: "mt-2"
};
const _hoisted_5$5 = {
  key: 0,
  class: "mt-2"
};
const _hoisted_6$2 = {
  key: 0,
  class: "mt-2"
};
const _hoisted_7$2 = { key: 0 };
const {ref: ref$a,toRaw: toRaw$4} = await importShared('vue');

const _sfc_main$e = /* @__PURE__ */ _defineComponent$e({
  __name: "ProxiesDialog",
  props: {
    proxyData: {
      type: Object,
      required: true
    },
    api: {
      type: Object,
      required: true
    }
  },
  emits: ["close", "refresh", "show-snackbar", "show-error"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const proxyForm = ref$a(null);
    const loading = ref$a(false);
    const tab = ref$a("general");
    const proxy = ref$a(structuredClone(toRaw$4(props.proxyData.data)));
    const wsHeaderString = ref$a("");
    const httpHeaderString = ref$a("");
    const jsonValidator = (value) => {
      if (!value) return true;
      try {
        JSON.parse(value);
        return true;
      } catch (e) {
        return "无效的JSON格式";
      }
    };
    const proxyTypes = [
      "ss",
      "ssr",
      "vmess",
      "vless",
      "trojan",
      "http",
      "snell",
      "tuic",
      "hysteria",
      "hysteria2"
    ];
    const initNestedObjects = () => {
      if (!proxy.value.smux) {
        proxy.value.smux = { enabled: false, protocol: "h2mux" };
      }
      if (!proxy.value.smux["brutal-opts"]) {
        proxy.value.smux["brutal-opts"] = { enabled: false };
      }
      if (!proxy.value["ws-opts"]) {
        proxy.value["ws-opts"] = {
          path: "/",
          "v2ray-http-upgrade": false,
          "v2ray-http-upgrade-fast-open": false
        };
      }
      if (!proxy.value["http-opts"]) {
        proxy.value["http-opts"] = { path: ["/"], method: "GET" };
      }
      if (!proxy.value["h2-opts"]) {
        proxy.value["h2-opts"] = { path: "/", host: [] };
      }
      if (!proxy.value["grpc-opts"]) {
        proxy.value["grpc-opts"] = { "grpc-service-name": "" };
      }
      if (!proxy.value.alpn) {
        proxy.value.alpn = [];
      }
      if (proxy.value["ws-opts"]?.headers) {
        wsHeaderString.value = JSON.stringify(proxy.value["ws-opts"].headers, null, 2);
      }
      if (proxy.value["http-opts"]?.headers) {
        httpHeaderString.value = JSON.stringify(proxy.value["http-opts"].headers, null, 2);
      }
    };
    initNestedObjects();
    const parseHeaders = () => {
      if (proxy.value.network === "ws") {
        try {
          if (proxy.value["ws-opts"]) {
            proxy.value["ws-opts"].headers = JSON.parse(wsHeaderString.value || "{}");
          }
        } catch (e) {
          console.error("Invalid JSON format for ws headers:", e);
          if (proxy.value["ws-opts"]) {
            proxy.value["ws-opts"].headers = {};
          }
        }
      }
      if (proxy.value.network === "http") {
        try {
          if (proxy.value["http-opts"]) {
            proxy.value["http-opts"].headers = JSON.parse(httpHeaderString.value || "{}");
          }
        } catch (e) {
          console.error("Invalid JSON format for http headers:", e);
          if (proxy.value["http-opts"]) {
            proxy.value["http-opts"].headers = {};
          }
        }
      }
    };
    const handleSave = async () => {
      const { valid } = await proxyForm.value.validate();
      if (valid) {
        parseHeaders();
        const finalProxy = { ...proxy.value };
        if (finalProxy.network !== "ws") delete finalProxy["ws-opts"];
        if (finalProxy.network !== "http") delete finalProxy["http-opts"];
        if (finalProxy.network !== "h2") delete finalProxy["h2-opts"];
        if (finalProxy.network !== "grpc") delete finalProxy["grpc-opts"];
        if (!finalProxy.smux?.enabled) {
          delete finalProxy.smux;
        } else if (!finalProxy.smux["brutal-opts"]?.enabled) {
          delete finalProxy.smux["brutal-opts"];
        }
        if (!finalProxy.tls) {
          delete finalProxy.servername;
          delete finalProxy.fingerprint;
          delete finalProxy.alpn;
          delete finalProxy["skip-cert-verify"];
          delete finalProxy["client-fingerprint"];
          delete finalProxy.sni;
        } else {
          if (["vmess", "vless"].includes(finalProxy.type)) {
            delete finalProxy.sni;
          } else {
            delete finalProxy.servername;
          }
          if (!["vmess", "vless", "trojan"].includes(finalProxy.type)) {
            delete finalProxy["client-fingerprint"];
          }
        }
        await saveProxy(finalProxy);
      }
    };
    const saveProxy = async (proxy2) => {
      loading.value = true;
      try {
        const requestData = {
          source: props.proxyData?.meta.source,
          proxy: proxy2
        };
        const name = encodeURIComponent(props.proxyData.data.name);
        const result = await props.api.patch(`/plugin/ClashRuleProvider/proxies/${name}`, requestData);
        if (!result.success) {
          emit("show-error", "保存出站代理失败: " + (result.message || "未知错误"));
          emit("show-snackbar", {
            show: true,
            message: "保存出站代理失败",
            color: "error"
          });
          return;
        }
        emit("refresh");
        emit("show-snackbar", {
          show: true,
          message: "出站代理更新成功",
          color: "success"
        });
        emit("close");
      } catch (err) {
        if (err instanceof Error) emit("show-error", "保存 Proxy 失败: " + (err.message || "未知错误"));
        emit("show-snackbar", {
          show: true,
          message: "保存代理失败",
          color: "error"
        });
      } finally {
        loading.value = false;
      }
    };
    return (_ctx, _cache) => {
      const _component_v_card_title = _resolveComponent$e("v-card-title");
      const _component_v_tab = _resolveComponent$e("v-tab");
      const _component_v_tabs = _resolveComponent$e("v-tabs");
      const _component_v_text_field = _resolveComponent$e("v-text-field");
      const _component_v_col = _resolveComponent$e("v-col");
      const _component_v_select = _resolveComponent$e("v-select");
      const _component_v_switch = _resolveComponent$e("v-switch");
      const _component_v_row = _resolveComponent$e("v-row");
      const _component_v_container = _resolveComponent$e("v-container");
      const _component_v_window_item = _resolveComponent$e("v-window-item");
      const _component_v_combobox = _resolveComponent$e("v-combobox");
      const _component_v_expand_transition = _resolveComponent$e("v-expand-transition");
      const _component_v_textarea = _resolveComponent$e("v-textarea");
      const _component_v_card_text = _resolveComponent$e("v-card-text");
      const _component_v_card = _resolveComponent$e("v-card");
      const _component_v_window = _resolveComponent$e("v-window");
      const _component_v_form = _resolveComponent$e("v-form");
      const _component_v_alert = _resolveComponent$e("v-alert");
      const _component_v_spacer = _resolveComponent$e("v-spacer");
      const _component_v_btn = _resolveComponent$e("v-btn");
      const _component_v_card_actions = _resolveComponent$e("v-card-actions");
      const _component_v_dialog = _resolveComponent$e("v-dialog");
      return _openBlock$e(), _createBlock$e(_component_v_dialog, {
        "max-width": "50rem",
        persistent: ""
      }, {
        default: _withCtx$e(() => [
          _createVNode$e(_component_v_card, null, {
            default: _withCtx$e(() => [
              _createVNode$e(_component_v_card_title, null, {
                default: _withCtx$e(() => _cache[45] || (_cache[45] = [
                  _createTextVNode$e("编辑代理")
                ])),
                _: 1
              }),
              _createVNode$e(_component_v_card_text, { class: "pa-2" }, {
                default: _withCtx$e(() => [
                  _createVNode$e(_component_v_form, {
                    ref_key: "proxyForm",
                    ref: proxyForm,
                    onSubmit: _withModifiers$2(handleSave, ["prevent"])
                  }, {
                    default: _withCtx$e(() => [
                      _createVNode$e(_component_v_tabs, {
                        modelValue: tab.value,
                        "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => tab.value = $event),
                        "background-color": "primary",
                        dark: "",
                        grow: ""
                      }, {
                        default: _withCtx$e(() => [
                          _createVNode$e(_component_v_tab, { value: "general" }, {
                            default: _withCtx$e(() => _cache[46] || (_cache[46] = [
                              _createTextVNode$e("通用")
                            ])),
                            _: 1
                          }),
                          _createVNode$e(_component_v_tab, { value: "tls" }, {
                            default: _withCtx$e(() => _cache[47] || (_cache[47] = [
                              _createTextVNode$e("TLS")
                            ])),
                            _: 1
                          }),
                          _createVNode$e(_component_v_tab, { value: "transport" }, {
                            default: _withCtx$e(() => _cache[48] || (_cache[48] = [
                              _createTextVNode$e("传输层")
                            ])),
                            _: 1
                          })
                        ]),
                        _: 1
                      }, 8, ["modelValue"]),
                      _createVNode$e(_component_v_window, {
                        modelValue: tab.value,
                        "onUpdate:modelValue": _cache[43] || (_cache[43] = ($event) => tab.value = $event),
                        class: "pt-4"
                      }, {
                        default: _withCtx$e(() => [
                          _createVNode$e(_component_v_window_item, { value: "general" }, {
                            default: _withCtx$e(() => [
                              _createVNode$e(_component_v_container, { fluid: "" }, {
                                default: _withCtx$e(() => [
                                  _createVNode$e(_component_v_row, { dense: "" }, {
                                    default: _withCtx$e(() => [
                                      _createVNode$e(_component_v_col, {
                                        cols: "12",
                                        md: "6"
                                      }, {
                                        default: _withCtx$e(() => [
                                          _createVNode$e(_component_v_text_field, {
                                            modelValue: proxy.value.name,
                                            "onUpdate:modelValue": _cache[1] || (_cache[1] = ($event) => proxy.value.name = $event),
                                            disabled: "",
                                            label: "名称 (name)",
                                            rules: [(v) => !!v || "名称不能为空"],
                                            hint: "代理名称",
                                            variant: "outlined"
                                          }, null, 8, ["modelValue", "rules"])
                                        ]),
                                        _: 1
                                      }),
                                      _createVNode$e(_component_v_col, {
                                        cols: "12",
                                        md: "6"
                                      }, {
                                        default: _withCtx$e(() => [
                                          _createVNode$e(_component_v_select, {
                                            modelValue: proxy.value.type,
                                            "onUpdate:modelValue": _cache[2] || (_cache[2] = ($event) => proxy.value.type = $event),
                                            label: "类型 (type)",
                                            items: proxyTypes,
                                            rules: [(v) => !!v || "类型不能为空"],
                                            hint: "代理协议类型",
                                            variant: "outlined"
                                          }, null, 8, ["modelValue", "rules"])
                                        ]),
                                        _: 1
                                      }),
                                      _createVNode$e(_component_v_col, {
                                        cols: "12",
                                        md: "6"
                                      }, {
                                        default: _withCtx$e(() => [
                                          _createVNode$e(_component_v_text_field, {
                                            modelValue: proxy.value.server,
                                            "onUpdate:modelValue": _cache[3] || (_cache[3] = ($event) => proxy.value.server = $event),
                                            label: "服务器 (server)",
                                            rules: [(v) => !!v || "服务器地址不能为空"],
                                            hint: "代理服务器地址 (域名/IP)",
                                            variant: "outlined"
                                          }, null, 8, ["modelValue", "rules"])
                                        ]),
                                        _: 1
                                      }),
                                      _createVNode$e(_component_v_col, {
                                        cols: "12",
                                        md: "6"
                                      }, {
                                        default: _withCtx$e(() => [
                                          _createVNode$e(_component_v_text_field, {
                                            modelValue: proxy.value.port,
                                            "onUpdate:modelValue": _cache[4] || (_cache[4] = ($event) => proxy.value.port = $event),
                                            modelModifiers: { number: true },
                                            label: "端口 (port)",
                                            type: "number",
                                            rules: [(v) => !!v || "端口不能为空"],
                                            hint: "代理服务器端口",
                                            variant: "outlined"
                                          }, null, 8, ["modelValue", "rules"])
                                        ]),
                                        _: 1
                                      }),
                                      _createVNode$e(_component_v_col, {
                                        cols: "12",
                                        md: "6"
                                      }, {
                                        default: _withCtx$e(() => [
                                          _createVNode$e(_component_v_select, {
                                            modelValue: proxy.value["ip-version"],
                                            "onUpdate:modelValue": _cache[5] || (_cache[5] = ($event) => proxy.value["ip-version"] = $event),
                                            label: "IP版本 (ip-version)",
                                            items: ["dual", "ipv4", "ipv6", "ipv4-prefer", "ipv6-prefer"],
                                            hint: "出站使用的IP版本",
                                            clearable: "",
                                            variant: "outlined"
                                          }, null, 8, ["modelValue"])
                                        ]),
                                        _: 1
                                      }),
                                      _createVNode$e(_component_v_col, {
                                        cols: "12",
                                        md: "6"
                                      }, {
                                        default: _withCtx$e(() => [
                                          _createVNode$e(_component_v_text_field, {
                                            modelValue: proxy.value["interface-name"],
                                            "onUpdate:modelValue": _cache[6] || (_cache[6] = ($event) => proxy.value["interface-name"] = $event),
                                            label: "网络接口 (interface-name)",
                                            hint: "指定出站网络接口",
                                            clearable: "",
                                            variant: "outlined"
                                          }, null, 8, ["modelValue"])
                                        ]),
                                        _: 1
                                      }),
                                      _createVNode$e(_component_v_col, {
                                        cols: "12",
                                        md: "6"
                                      }, {
                                        default: _withCtx$e(() => [
                                          _createVNode$e(_component_v_text_field, {
                                            modelValue: proxy.value["routing-mark"],
                                            "onUpdate:modelValue": _cache[7] || (_cache[7] = ($event) => proxy.value["routing-mark"] = $event),
                                            modelModifiers: { number: true },
                                            label: "路由标记 (routing-mark)",
                                            type: "number",
                                            hint: "为出站连接设置路由标记",
                                            clearable: "",
                                            variant: "outlined"
                                          }, null, 8, ["modelValue"])
                                        ]),
                                        _: 1
                                      }),
                                      _createVNode$e(_component_v_col, {
                                        cols: "12",
                                        md: "6"
                                      }, {
                                        default: _withCtx$e(() => [
                                          _createVNode$e(_component_v_text_field, {
                                            modelValue: proxy.value["dialer-proxy"],
                                            "onUpdate:modelValue": _cache[8] || (_cache[8] = ($event) => proxy.value["dialer-proxy"] = $event),
                                            label: "拨号代理 (dialer-proxy)",
                                            hint: "指定当前代理通过哪个代理建立连接",
                                            clearable: "",
                                            variant: "outlined"
                                          }, null, 8, ["modelValue"])
                                        ]),
                                        _: 1
                                      }),
                                      _createVNode$e(_component_v_col, {
                                        cols: "4",
                                        sm: "4"
                                      }, {
                                        default: _withCtx$e(() => [
                                          _createVNode$e(_component_v_switch, {
                                            modelValue: proxy.value.udp,
                                            "onUpdate:modelValue": _cache[9] || (_cache[9] = ($event) => proxy.value.udp = $event),
                                            label: "UDP",
                                            hint: "是否允许UDP",
                                            inset: "",
                                            color: "primary"
                                          }, null, 8, ["modelValue"])
                                        ]),
                                        _: 1
                                      }),
                                      _createVNode$e(_component_v_col, {
                                        cols: "4",
                                        sm: "4"
                                      }, {
                                        default: _withCtx$e(() => [
                                          _createVNode$e(_component_v_switch, {
                                            modelValue: proxy.value.tfo,
                                            "onUpdate:modelValue": _cache[10] || (_cache[10] = ($event) => proxy.value.tfo = $event),
                                            label: "TFO",
                                            hint: "启用 TCP Fast Open",
                                            inset: "",
                                            color: "primary"
                                          }, null, 8, ["modelValue"])
                                        ]),
                                        _: 1
                                      }),
                                      _createVNode$e(_component_v_col, {
                                        cols: "4",
                                        sm: "4"
                                      }, {
                                        default: _withCtx$e(() => [
                                          _createVNode$e(_component_v_switch, {
                                            modelValue: proxy.value.mptcp,
                                            "onUpdate:modelValue": _cache[11] || (_cache[11] = ($event) => proxy.value.mptcp = $event),
                                            label: "MPTCP",
                                            hint: "启用 Multi-Path TCP",
                                            inset: "",
                                            color: "primary"
                                          }, null, 8, ["modelValue"])
                                        ]),
                                        _: 1
                                      })
                                    ]),
                                    _: 1
                                  })
                                ]),
                                _: 1
                              })
                            ]),
                            _: 1
                          }),
                          _createVNode$e(_component_v_window_item, { value: "tls" }, {
                            default: _withCtx$e(() => [
                              _createVNode$e(_component_v_container, { fluid: "" }, {
                                default: _withCtx$e(() => [
                                  _createVNode$e(_component_v_row, { dense: "" }, {
                                    default: _withCtx$e(() => [
                                      _createVNode$e(_component_v_col, { cols: "12" }, {
                                        default: _withCtx$e(() => [
                                          _createVNode$e(_component_v_switch, {
                                            modelValue: proxy.value.tls,
                                            "onUpdate:modelValue": _cache[12] || (_cache[12] = ($event) => proxy.value.tls = $event),
                                            label: "启用 TLS",
                                            inset: "",
                                            color: "primary"
                                          }, null, 8, ["modelValue"])
                                        ]),
                                        _: 1
                                      })
                                    ]),
                                    _: 1
                                  }),
                                  _createVNode$e(_component_v_expand_transition, null, {
                                    default: _withCtx$e(() => [
                                      proxy.value.tls ? (_openBlock$e(), _createElementBlock$7("div", _hoisted_1$a, [
                                        _createVNode$e(_component_v_row, { dense: "" }, {
                                          default: _withCtx$e(() => [
                                            _createVNode$e(_component_v_col, {
                                              cols: "12",
                                              md: "6"
                                            }, {
                                              default: _withCtx$e(() => [
                                                ["vmess", "vless"].includes(proxy.value.type) ? (_openBlock$e(), _createBlock$e(_component_v_text_field, {
                                                  key: 0,
                                                  modelValue: proxy.value.servername,
                                                  "onUpdate:modelValue": _cache[13] || (_cache[13] = ($event) => proxy.value.servername = $event),
                                                  label: "服务器名称 (servername)",
                                                  hint: "TLS服务器名称(SNI)",
                                                  clearable: "",
                                                  "persistent-hint": "",
                                                  variant: "outlined"
                                                }, null, 8, ["modelValue"])) : (_openBlock$e(), _createBlock$e(_component_v_text_field, {
                                                  key: 1,
                                                  modelValue: proxy.value.sni,
                                                  "onUpdate:modelValue": _cache[14] || (_cache[14] = ($event) => proxy.value.sni = $event),
                                                  label: "SNI",
                                                  hint: "TLS服务器名称(SNI)",
                                                  clearable: "",
                                                  "persistent-hint": "",
                                                  variant: "outlined"
                                                }, null, 8, ["modelValue"]))
                                              ]),
                                              _: 1
                                            }),
                                            _createVNode$e(_component_v_col, {
                                              cols: "12",
                                              md: "6"
                                            }, {
                                              default: _withCtx$e(() => [
                                                _createVNode$e(_component_v_text_field, {
                                                  modelValue: proxy.value.fingerprint,
                                                  "onUpdate:modelValue": _cache[15] || (_cache[15] = ($event) => proxy.value.fingerprint = $event),
                                                  label: "指纹 (fingerprint)",
                                                  hint: "证书指纹",
                                                  clearable: "",
                                                  "persistent-hint": "",
                                                  variant: "outlined"
                                                }, null, 8, ["modelValue"])
                                              ]),
                                              _: 1
                                            }),
                                            _createVNode$e(_component_v_col, { cols: "12" }, {
                                              default: _withCtx$e(() => [
                                                _createVNode$e(_component_v_combobox, {
                                                  modelValue: proxy.value.alpn,
                                                  "onUpdate:modelValue": _cache[16] || (_cache[16] = ($event) => proxy.value.alpn = $event),
                                                  label: "ALPN",
                                                  hint: "应用层协议协商",
                                                  multiple: "",
                                                  chips: "",
                                                  clearable: "",
                                                  "deletable-chips": "",
                                                  "persistent-hint": "",
                                                  variant: "outlined"
                                                }, null, 8, ["modelValue"])
                                              ]),
                                              _: 1
                                            }),
                                            ["vmess", "vless", "trojan"].includes(proxy.value.type) ? (_openBlock$e(), _createBlock$e(_component_v_col, {
                                              key: 0,
                                              cols: "12",
                                              md: "6"
                                            }, {
                                              default: _withCtx$e(() => [
                                                _createVNode$e(_component_v_select, {
                                                  modelValue: proxy.value["client-fingerprint"],
                                                  "onUpdate:modelValue": _cache[17] || (_cache[17] = ($event) => proxy.value["client-fingerprint"] = $event),
                                                  label: "客户端指纹 (client-fingerprint)",
                                                  items: [
                                                    "chrome",
                                                    "firefox",
                                                    "safari",
                                                    "ios",
                                                    "android",
                                                    "edge",
                                                    "360",
                                                    "qq",
                                                    "random"
                                                  ],
                                                  hint: "uTLS客户端指紋",
                                                  clearable: "",
                                                  "persistent-hint": "",
                                                  variant: "outlined"
                                                }, null, 8, ["modelValue"])
                                              ]),
                                              _: 1
                                            })) : _createCommentVNode$b("", true),
                                            _createVNode$e(_component_v_col, {
                                              cols: "12",
                                              md: "6",
                                              class: "d-flex align-center"
                                            }, {
                                              default: _withCtx$e(() => [
                                                _createVNode$e(_component_v_switch, {
                                                  modelValue: proxy.value["skip-cert-verify"],
                                                  "onUpdate:modelValue": _cache[18] || (_cache[18] = ($event) => proxy.value["skip-cert-verify"] = $event),
                                                  label: "跳过证书验证",
                                                  inset: "",
                                                  "persistent-hint": "",
                                                  color: "primary"
                                                }, null, 8, ["modelValue"])
                                              ]),
                                              _: 1
                                            })
                                          ]),
                                          _: 1
                                        })
                                      ])) : _createCommentVNode$b("", true)
                                    ]),
                                    _: 1
                                  })
                                ]),
                                _: 1
                              })
                            ]),
                            _: 1
                          }),
                          _createVNode$e(_component_v_window_item, { value: "transport" }, {
                            default: _withCtx$e(() => [
                              _createVNode$e(_component_v_container, { fluid: "" }, {
                                default: _withCtx$e(() => [
                                  _createVNode$e(_component_v_row, null, {
                                    default: _withCtx$e(() => [
                                      _createVNode$e(_component_v_col, { cols: "12" }, {
                                        default: _withCtx$e(() => [
                                          _createVNode$e(_component_v_select, {
                                            modelValue: proxy.value.network,
                                            "onUpdate:modelValue": _cache[19] || (_cache[19] = ($event) => proxy.value.network = $event),
                                            label: "网络 (network)",
                                            items: ["http", "h2", "grpc", "ws"],
                                            hint: "传输层协议",
                                            clearable: "",
                                            "persistent-hint": "",
                                            variant: "outlined"
                                          }, null, 8, ["modelValue"])
                                        ]),
                                        _: 1
                                      })
                                    ]),
                                    _: 1
                                  }),
                                  _createVNode$e(_component_v_expand_transition, null, {
                                    default: _withCtx$e(() => [
                                      proxy.value.network === "ws" && proxy.value["ws-opts"] ? (_openBlock$e(), _createElementBlock$7("div", _hoisted_2$8, [
                                        _createVNode$e(_component_v_card, { variant: "tonal" }, {
                                          default: _withCtx$e(() => [
                                            _createVNode$e(_component_v_card_title, { class: "text-subtitle-1 py-2" }, {
                                              default: _withCtx$e(() => _cache[49] || (_cache[49] = [
                                                _createTextVNode$e("WebSocket 选项")
                                              ])),
                                              _: 1
                                            }),
                                            _createVNode$e(_component_v_card_text, null, {
                                              default: _withCtx$e(() => [
                                                _createVNode$e(_component_v_row, null, {
                                                  default: _withCtx$e(() => [
                                                    _createVNode$e(_component_v_col, {
                                                      cols: "12",
                                                      md: "6"
                                                    }, {
                                                      default: _withCtx$e(() => [
                                                        _createVNode$e(_component_v_switch, {
                                                          modelValue: proxy.value["ws-opts"]["v2ray-http-upgrade"],
                                                          "onUpdate:modelValue": _cache[20] || (_cache[20] = ($event) => proxy.value["ws-opts"]["v2ray-http-upgrade"] = $event),
                                                          label: "v2ray-http-upgrade",
                                                          hint: "启用 http upgrade",
                                                          inset: "",
                                                          color: "primary"
                                                        }, null, 8, ["modelValue"])
                                                      ]),
                                                      _: 1
                                                    }),
                                                    _createVNode$e(_component_v_col, {
                                                      cols: "12",
                                                      md: "6"
                                                    }, {
                                                      default: _withCtx$e(() => [
                                                        _createVNode$e(_component_v_switch, {
                                                          modelValue: proxy.value["ws-opts"]["v2ray-http-upgrade-fast-open"],
                                                          "onUpdate:modelValue": _cache[21] || (_cache[21] = ($event) => proxy.value["ws-opts"]["v2ray-http-upgrade-fast-open"] = $event),
                                                          label: "v2ray-http-upgrade-fast-open",
                                                          hint: "启用 http upgrade 的 fast open",
                                                          inset: "",
                                                          color: "primary"
                                                        }, null, 8, ["modelValue"])
                                                      ]),
                                                      _: 1
                                                    })
                                                  ]),
                                                  _: 1
                                                }),
                                                _createVNode$e(_component_v_text_field, {
                                                  modelValue: proxy.value["ws-opts"].path,
                                                  "onUpdate:modelValue": _cache[22] || (_cache[22] = ($event) => proxy.value["ws-opts"].path = $event),
                                                  label: "路径 (path)",
                                                  hint: "WebSocket请求路径",
                                                  variant: "outlined",
                                                  class: "mb-2"
                                                }, null, 8, ["modelValue"]),
                                                _createVNode$e(_component_v_text_field, {
                                                  modelValue: proxy.value["ws-opts"]["max-early-data"],
                                                  "onUpdate:modelValue": _cache[23] || (_cache[23] = ($event) => proxy.value["ws-opts"]["max-early-data"] = $event),
                                                  modelModifiers: { number: true },
                                                  label: "max-early-data",
                                                  type: "number",
                                                  hint: "Early Data 首包长度阈值",
                                                  variant: "outlined",
                                                  class: "mb-2",
                                                  clearable: ""
                                                }, null, 8, ["modelValue"]),
                                                _createVNode$e(_component_v_text_field, {
                                                  modelValue: proxy.value["ws-opts"]["early-data-header-name"],
                                                  "onUpdate:modelValue": _cache[24] || (_cache[24] = ($event) => proxy.value["ws-opts"]["early-data-header-name"] = $event),
                                                  label: "early-data-header-name",
                                                  variant: "outlined",
                                                  class: "mb-2",
                                                  clearable: ""
                                                }, null, 8, ["modelValue"]),
                                                _createVNode$e(_component_v_textarea, {
                                                  modelValue: wsHeaderString.value,
                                                  "onUpdate:modelValue": _cache[25] || (_cache[25] = ($event) => wsHeaderString.value = $event),
                                                  label: "请求头 (headers)",
                                                  hint: '请输入JSON格式字符串, 例如: {"Host":"example.com"}',
                                                  variant: "outlined",
                                                  rows: "3",
                                                  rules: [jsonValidator]
                                                }, null, 8, ["modelValue", "rules"])
                                              ]),
                                              _: 1
                                            })
                                          ]),
                                          _: 1
                                        })
                                      ])) : _createCommentVNode$b("", true)
                                    ]),
                                    _: 1
                                  }),
                                  _createVNode$e(_component_v_expand_transition, null, {
                                    default: _withCtx$e(() => [
                                      proxy.value.network === "http" && proxy.value["http-opts"] ? (_openBlock$e(), _createElementBlock$7("div", _hoisted_3$8, [
                                        _createVNode$e(_component_v_card, { variant: "tonal" }, {
                                          default: _withCtx$e(() => [
                                            _createVNode$e(_component_v_card_title, { class: "text-subtitle-1 py-2" }, {
                                              default: _withCtx$e(() => _cache[50] || (_cache[50] = [
                                                _createTextVNode$e("HTTP 选项")
                                              ])),
                                              _: 1
                                            }),
                                            _createVNode$e(_component_v_card_text, null, {
                                              default: _withCtx$e(() => [
                                                _createVNode$e(_component_v_text_field, {
                                                  modelValue: proxy.value["http-opts"].method,
                                                  "onUpdate:modelValue": _cache[26] || (_cache[26] = ($event) => proxy.value["http-opts"].method = $event),
                                                  label: "方法 (method)",
                                                  hint: "HTTP请求方法",
                                                  variant: "outlined",
                                                  class: "mb-2"
                                                }, null, 8, ["modelValue"]),
                                                _createVNode$e(_component_v_combobox, {
                                                  modelValue: proxy.value["http-opts"].path,
                                                  "onUpdate:modelValue": _cache[27] || (_cache[27] = ($event) => proxy.value["http-opts"].path = $event),
                                                  label: "路径 (path)",
                                                  hint: "HTTP请求路径",
                                                  multiple: "",
                                                  chips: "",
                                                  clearable: "",
                                                  "deletable-chips": "",
                                                  variant: "outlined",
                                                  class: "mb-2"
                                                }, null, 8, ["modelValue"]),
                                                _createVNode$e(_component_v_textarea, {
                                                  modelValue: httpHeaderString.value,
                                                  "onUpdate:modelValue": _cache[28] || (_cache[28] = ($event) => httpHeaderString.value = $event),
                                                  label: "请求头 (headers)",
                                                  hint: '请输入JSON格式字符串, 例如: {"Host":"example.com"}',
                                                  variant: "outlined",
                                                  rows: "3",
                                                  rules: [jsonValidator]
                                                }, null, 8, ["modelValue", "rules"])
                                              ]),
                                              _: 1
                                            })
                                          ]),
                                          _: 1
                                        })
                                      ])) : _createCommentVNode$b("", true)
                                    ]),
                                    _: 1
                                  }),
                                  _createVNode$e(_component_v_expand_transition, null, {
                                    default: _withCtx$e(() => [
                                      proxy.value.network === "h2" && proxy.value["h2-opts"] ? (_openBlock$e(), _createElementBlock$7("div", _hoisted_4$8, [
                                        _createVNode$e(_component_v_card, { variant: "tonal" }, {
                                          default: _withCtx$e(() => [
                                            _createVNode$e(_component_v_card_title, { class: "text-subtitle-1 py-2" }, {
                                              default: _withCtx$e(() => _cache[51] || (_cache[51] = [
                                                _createTextVNode$e("H2 选项")
                                              ])),
                                              _: 1
                                            }),
                                            _createVNode$e(_component_v_card_text, null, {
                                              default: _withCtx$e(() => [
                                                _createVNode$e(_component_v_text_field, {
                                                  modelValue: proxy.value["h2-opts"].path,
                                                  "onUpdate:modelValue": _cache[29] || (_cache[29] = ($event) => proxy.value["h2-opts"].path = $event),
                                                  label: "路径 (path)",
                                                  hint: "H2请求路径",
                                                  variant: "outlined",
                                                  class: "mb-2"
                                                }, null, 8, ["modelValue"]),
                                                _createVNode$e(_component_v_combobox, {
                                                  modelValue: proxy.value["h2-opts"].host,
                                                  "onUpdate:modelValue": _cache[30] || (_cache[30] = ($event) => proxy.value["h2-opts"].host = $event),
                                                  label: "主机 (host)",
                                                  hint: "主机域名列表",
                                                  multiple: "",
                                                  chips: "",
                                                  clearable: "",
                                                  "deletable-chips": "",
                                                  variant: "outlined"
                                                }, null, 8, ["modelValue"])
                                              ]),
                                              _: 1
                                            })
                                          ]),
                                          _: 1
                                        })
                                      ])) : _createCommentVNode$b("", true)
                                    ]),
                                    _: 1
                                  }),
                                  _createVNode$e(_component_v_expand_transition, null, {
                                    default: _withCtx$e(() => [
                                      proxy.value.network === "grpc" && proxy.value["grpc-opts"] ? (_openBlock$e(), _createElementBlock$7("div", _hoisted_5$5, [
                                        _createVNode$e(_component_v_card, { variant: "tonal" }, {
                                          default: _withCtx$e(() => [
                                            _createVNode$e(_component_v_card_title, { class: "text-subtitle-1 py-2" }, {
                                              default: _withCtx$e(() => _cache[52] || (_cache[52] = [
                                                _createTextVNode$e("gRPC 选项")
                                              ])),
                                              _: 1
                                            }),
                                            _createVNode$e(_component_v_card_text, null, {
                                              default: _withCtx$e(() => [
                                                _createVNode$e(_component_v_text_field, {
                                                  modelValue: proxy.value["grpc-opts"]["grpc-service-name"],
                                                  "onUpdate:modelValue": _cache[31] || (_cache[31] = ($event) => proxy.value["grpc-opts"]["grpc-service-name"] = $event),
                                                  label: "服务名称 (grpc-service-name)",
                                                  hint: "gRPC服务名称",
                                                  variant: "outlined"
                                                }, null, 8, ["modelValue"])
                                              ]),
                                              _: 1
                                            })
                                          ]),
                                          _: 1
                                        })
                                      ])) : _createCommentVNode$b("", true)
                                    ]),
                                    _: 1
                                  }),
                                  _createVNode$e(_component_v_expand_transition, null, {
                                    default: _withCtx$e(() => [
                                      (!proxy.value.network || proxy.value.network === "tcp") && proxy.value.smux ? (_openBlock$e(), _createElementBlock$7("div", _hoisted_6$2, [
                                        _createVNode$e(_component_v_card, { variant: "tonal" }, {
                                          default: _withCtx$e(() => [
                                            _createVNode$e(_component_v_card_title, { class: "text-subtitle-1 py-2" }, {
                                              default: _withCtx$e(() => _cache[53] || (_cache[53] = [
                                                _createTextVNode$e("Smux 选项")
                                              ])),
                                              _: 1
                                            }),
                                            _createVNode$e(_component_v_card_text, null, {
                                              default: _withCtx$e(() => [
                                                _createVNode$e(_component_v_row, { dense: "" }, {
                                                  default: _withCtx$e(() => [
                                                    _createVNode$e(_component_v_col, { cols: "12" }, {
                                                      default: _withCtx$e(() => [
                                                        _createVNode$e(_component_v_switch, {
                                                          modelValue: proxy.value.smux.enabled,
                                                          "onUpdate:modelValue": _cache[32] || (_cache[32] = ($event) => proxy.value.smux.enabled = $event),
                                                          label: "启用 Smux",
                                                          inset: "",
                                                          color: "primary"
                                                        }, null, 8, ["modelValue"])
                                                      ]),
                                                      _: 1
                                                    })
                                                  ]),
                                                  _: 1
                                                }),
                                                _createVNode$e(_component_v_expand_transition, null, {
                                                  default: _withCtx$e(() => [
                                                    proxy.value.smux.enabled && proxy.value.smux["brutal-opts"] ? (_openBlock$e(), _createElementBlock$7("div", _hoisted_7$2, [
                                                      _createVNode$e(_component_v_row, { dense: "" }, {
                                                        default: _withCtx$e(() => [
                                                          _createVNode$e(_component_v_col, {
                                                            cols: "12",
                                                            md: "6"
                                                          }, {
                                                            default: _withCtx$e(() => [
                                                              _createVNode$e(_component_v_select, {
                                                                modelValue: proxy.value.smux.protocol,
                                                                "onUpdate:modelValue": _cache[33] || (_cache[33] = ($event) => proxy.value.smux.protocol = $event),
                                                                label: "协议 (protocol)",
                                                                items: ["smux", "yamux", "h2mux"],
                                                                hint: "Smux协议类型",
                                                                variant: "outlined"
                                                              }, null, 8, ["modelValue"])
                                                            ]),
                                                            _: 1
                                                          }),
                                                          _createVNode$e(_component_v_col, {
                                                            cols: "12",
                                                            md: "6"
                                                          }, {
                                                            default: _withCtx$e(() => [
                                                              _createVNode$e(_component_v_text_field, {
                                                                modelValue: proxy.value.smux["max-connections"],
                                                                "onUpdate:modelValue": _cache[34] || (_cache[34] = ($event) => proxy.value.smux["max-connections"] = $event),
                                                                modelModifiers: { number: true },
                                                                label: "最大连接数 (max-connections)",
                                                                type: "number",
                                                                hint: "最大复用连接数",
                                                                clearable: "",
                                                                variant: "outlined"
                                                              }, null, 8, ["modelValue"])
                                                            ]),
                                                            _: 1
                                                          }),
                                                          _createVNode$e(_component_v_col, {
                                                            cols: "12",
                                                            md: "6"
                                                          }, {
                                                            default: _withCtx$e(() => [
                                                              _createVNode$e(_component_v_text_field, {
                                                                modelValue: proxy.value.smux["min-streams"],
                                                                "onUpdate:modelValue": _cache[35] || (_cache[35] = ($event) => proxy.value.smux["min-streams"] = $event),
                                                                modelModifiers: { number: true },
                                                                label: "最小流数 (min-streams)",
                                                                type: "number",
                                                                hint: "每个连接的最小流数",
                                                                clearable: "",
                                                                variant: "outlined"
                                                              }, null, 8, ["modelValue"])
                                                            ]),
                                                            _: 1
                                                          }),
                                                          _createVNode$e(_component_v_col, {
                                                            cols: "12",
                                                            md: "6"
                                                          }, {
                                                            default: _withCtx$e(() => [
                                                              _createVNode$e(_component_v_text_field, {
                                                                modelValue: proxy.value.smux["max-streams"],
                                                                "onUpdate:modelValue": _cache[36] || (_cache[36] = ($event) => proxy.value.smux["max-streams"] = $event),
                                                                modelModifiers: { number: true },
                                                                label: "最大流数 (max-streams)",
                                                                type: "number",
                                                                hint: "每个连接的最大流数",
                                                                clearable: "",
                                                                variant: "outlined"
                                                              }, null, 8, ["modelValue"])
                                                            ]),
                                                            _: 1
                                                          }),
                                                          _createVNode$e(_component_v_col, {
                                                            cols: "4",
                                                            sm: "4"
                                                          }, {
                                                            default: _withCtx$e(() => [
                                                              _createVNode$e(_component_v_switch, {
                                                                modelValue: proxy.value.smux.padding,
                                                                "onUpdate:modelValue": _cache[37] || (_cache[37] = ($event) => proxy.value.smux.padding = $event),
                                                                label: "Padding",
                                                                hint: "启用Padding",
                                                                inset: "",
                                                                color: "primary"
                                                              }, null, 8, ["modelValue"])
                                                            ]),
                                                            _: 1
                                                          }),
                                                          _createVNode$e(_component_v_col, {
                                                            cols: "4",
                                                            sm: "4"
                                                          }, {
                                                            default: _withCtx$e(() => [
                                                              _createVNode$e(_component_v_switch, {
                                                                modelValue: proxy.value.smux.statistic,
                                                                "onUpdate:modelValue": _cache[38] || (_cache[38] = ($event) => proxy.value.smux.statistic = $event),
                                                                label: "Statistic",
                                                                hint: "启用统计",
                                                                inset: "",
                                                                color: "primary"
                                                              }, null, 8, ["modelValue"])
                                                            ]),
                                                            _: 1
                                                          }),
                                                          _createVNode$e(_component_v_col, {
                                                            cols: "4",
                                                            sm: "4"
                                                          }, {
                                                            default: _withCtx$e(() => [
                                                              _createVNode$e(_component_v_switch, {
                                                                modelValue: proxy.value.smux["only-tcp"],
                                                                "onUpdate:modelValue": _cache[39] || (_cache[39] = ($event) => proxy.value.smux["only-tcp"] = $event),
                                                                label: "Only TCP",
                                                                hint: "仅用于TCP",
                                                                inset: "",
                                                                color: "primary"
                                                              }, null, 8, ["modelValue"])
                                                            ]),
                                                            _: 1
                                                          }),
                                                          _createVNode$e(_component_v_col, { cols: "12" }, {
                                                            default: _withCtx$e(() => [
                                                              _createVNode$e(_component_v_switch, {
                                                                modelValue: proxy.value.smux["brutal-opts"].enabled,
                                                                "onUpdate:modelValue": _cache[40] || (_cache[40] = ($event) => proxy.value.smux["brutal-opts"].enabled = $event),
                                                                label: "启用 Brutal 优化",
                                                                inset: "",
                                                                color: "primary"
                                                              }, null, 8, ["modelValue"])
                                                            ]),
                                                            _: 1
                                                          })
                                                        ]),
                                                        _: 1
                                                      }),
                                                      _createVNode$e(_component_v_expand_transition, null, {
                                                        default: _withCtx$e(() => [
                                                          proxy.value.smux["brutal-opts"].enabled ? (_openBlock$e(), _createBlock$e(_component_v_row, {
                                                            key: 0,
                                                            dense: ""
                                                          }, {
                                                            default: _withCtx$e(() => [
                                                              _createVNode$e(_component_v_col, {
                                                                cols: "12",
                                                                md: "6"
                                                              }, {
                                                                default: _withCtx$e(() => [
                                                                  _createVNode$e(_component_v_text_field, {
                                                                    modelValue: proxy.value.smux["brutal-opts"].up,
                                                                    "onUpdate:modelValue": _cache[41] || (_cache[41] = ($event) => proxy.value.smux["brutal-opts"].up = $event),
                                                                    modelModifiers: { number: true },
                                                                    label: "上行带宽 (up)",
                                                                    hint: "上行带宽, 默认以 Mbps 为单位",
                                                                    clearable: "",
                                                                    variant: "outlined"
                                                                  }, null, 8, ["modelValue"])
                                                                ]),
                                                                _: 1
                                                              }),
                                                              _createVNode$e(_component_v_col, {
                                                                cols: "12",
                                                                md: "6"
                                                              }, {
                                                                default: _withCtx$e(() => [
                                                                  _createVNode$e(_component_v_text_field, {
                                                                    modelValue: proxy.value.smux["brutal-opts"].down,
                                                                    "onUpdate:modelValue": _cache[42] || (_cache[42] = ($event) => proxy.value.smux["brutal-opts"].down = $event),
                                                                    modelModifiers: { number: true },
                                                                    label: "下行带宽 (down)",
                                                                    hint: "下行带宽, 默认以 Mbps 为单位",
                                                                    clearable: "",
                                                                    variant: "outlined"
                                                                  }, null, 8, ["modelValue"])
                                                                ]),
                                                                _: 1
                                                              })
                                                            ]),
                                                            _: 1
                                                          })) : _createCommentVNode$b("", true)
                                                        ]),
                                                        _: 1
                                                      })
                                                    ])) : _createCommentVNode$b("", true)
                                                  ]),
                                                  _: 1
                                                })
                                              ]),
                                              _: 1
                                            })
                                          ]),
                                          _: 1
                                        })
                                      ])) : _createCommentVNode$b("", true)
                                    ]),
                                    _: 1
                                  })
                                ]),
                                _: 1
                              })
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      }, 8, ["modelValue"])
                    ]),
                    _: 1
                  }, 512),
                  _createVNode$e(_component_v_alert, {
                    type: "info",
                    variant: "tonal"
                  }, {
                    default: _withCtx$e(() => _cache[54] || (_cache[54] = [
                      _createTextVNode$e(" 参考"),
                      _createElementVNode$b("a", {
                        href: "https://wiki.metacubex.one/config/proxies/",
                        target: "_blank",
                        style: { "text-decoration": "underline" }
                      }, "Docs", -1),
                      _createTextVNode$e(", 覆写某些选项可能导致代理不可用。 ")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              }),
              _createVNode$e(_component_v_card_actions, null, {
                default: _withCtx$e(() => [
                  _createVNode$e(_component_v_spacer),
                  _createVNode$e(_component_v_btn, {
                    onClick: _cache[44] || (_cache[44] = ($event) => emit("close"))
                  }, {
                    default: _withCtx$e(() => _cache[55] || (_cache[55] = [
                      _createTextVNode$e("取消")
                    ])),
                    _: 1
                  }),
                  _createVNode$e(_component_v_btn, {
                    color: "primary",
                    loading: loading.value,
                    disabled: loading.value,
                    onClick: handleSave
                  }, {
                    default: _withCtx$e(() => _cache[56] || (_cache[56] = [
                      _createTextVNode$e("保存")
                    ])),
                    _: 1
                  }, 8, ["loading", "disabled"])
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _: 1
      });
    };
  }
});

const {defineComponent:_defineComponent$d} = await importShared('vue');

const {resolveComponent:_resolveComponent$d,createVNode:_createVNode$d,withCtx:_withCtx$d,createElementVNode:_createElementVNode$a,renderList:_renderList$6,Fragment:_Fragment$6,openBlock:_openBlock$d,createElementBlock:_createElementBlock$6,createBlock:_createBlock$d,unref:_unref$b,toDisplayString:_toDisplayString$c,createTextVNode:_createTextVNode$d,mergeProps:_mergeProps$a,createCommentVNode:_createCommentVNode$a} = await importShared('vue');

const _hoisted_1$9 = { class: "mb-2 position-relative" };
const _hoisted_2$7 = { class: "pa-4" };
const _hoisted_3$7 = { class: "d-none d-sm-flex clash-data-table" };
const _hoisted_4$7 = { class: "d-sm-none" };
const _hoisted_5$4 = {
  class: "pa-4",
  style: { "min-height": "4rem" }
};
const {ref: ref$9,computed: computed$3} = await importShared('vue');
const _sfc_main$d = /* @__PURE__ */ _defineComponent$d({
  __name: "ProxiesTab",
  props: {
    proxies: {},
    api: {}
  },
  emits: ["refresh", "show-snackbar", "show-error", "show-yaml", "copy-to-clipboard", "edit-visibility"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const editorOptions = {
      enableBasicAutocompletion: true,
      enableSnippets: true,
      enableLiveAutocompletion: true,
      showLineNumbers: true,
      tabSize: 2
    };
    const proxiesPlaceholder = ref$9(
      `proxies:
  - name: "ss node"
    type: "ss"`
    );
    const importProxiesTypes = ["YAML", "LINK"];
    const searchProxies = ref$9("");
    const pageProxies = ref$9(1);
    const itemsPerPageProxies = ref$9(10);
    const loading = ref$9(false);
    const filteredExtraProxies = computed$3(() => {
      if (!searchProxies.value) return props.proxies;
      const keyword = searchProxies.value.toLowerCase();
      return props.proxies.filter(
        (item) => Object.values(item).some((val) => String(val).toLowerCase().includes(keyword))
      );
    });
    const paginatedExtraProxies = computed$3(() => {
      const start = (pageProxies.value - 1) * itemsPerPageProxies.value;
      const end = start + itemsPerPageProxies.value;
      return filteredExtraProxies.value.slice(start, end);
    });
    const pageCountProxies = computed$3(() => {
      if (itemsPerPageProxies.value === -1) {
        return 1;
      }
      return Math.ceil(props.proxies.length / itemsPerPageProxies.value);
    });
    const importExtraProxiesPlaceholderText = computed$3(() => {
      return importProxies.value.type === "YAML" ? "proxies: []" : "vless://xxxx";
    });
    const importExtraProxiesDialog = ref$9(false);
    const importProxiesLoading = ref$9(false);
    const importProxies = ref$9({
      type: "YAML",
      payload: ""
    });
    function openImportProxiesDialog() {
      importProxies.value = {
        type: "YAML",
        payload: ""
      };
      importExtraProxiesDialog.value = true;
    }
    async function importExtraProxies() {
      try {
        importProxiesLoading.value = true;
        const requestData = {
          vehicle: importProxies.value.type,
          payload: importProxies.value.payload
        };
        const result = await props.api.put("/plugin/ClashRuleProvider/proxies", requestData);
        if (!result.success) {
          emit("show-error", "节点导入失败: " + (result.message || "未知错误"));
          emit("show-snackbar", {
            show: true,
            message: "节点导入失败",
            color: "error"
          });
          return;
        }
        importExtraProxiesDialog.value = false;
        emit("refresh", ["proxies", "clash-outbounds"]);
        emit("show-snackbar", {
          show: true,
          message: "节点导入成功",
          color: "success"
        });
      } catch (err) {
        if (err instanceof Error) emit("show-error", "节点导入失败: " + (err.message || "未知错误"));
        emit("show-snackbar", {
          show: true,
          message: "节点导入失败",
          color: "error"
        });
      } finally {
        importProxiesLoading.value = false;
      }
    }
    const proxiesDialogVisible = ref$9(false);
    const editingProxy = ref$9({
      meta: { ...defaultMetadata },
      data: { ...defaultProxy },
      name: defaultProxy.name
    });
    function openProxiesDialog(proxyData) {
      editingProxy.value = proxyData;
      proxiesDialogVisible.value = true;
    }
    function closeProxyDialog() {
      proxiesDialogVisible.value = false;
    }
    async function deleteProxy(name) {
      loading.value = true;
      try {
        await props.api.delete(`/plugin/ClashRuleProvider/proxies/${name}`);
        emit("refresh", ["proxies", "clash-outbounds"]);
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", err.message || "删除规则失败");
        }
      } finally {
        loading.value = false;
      }
    }
    async function deletePatch(name) {
      loading.value = true;
      try {
        const n = encodeURIComponent(name);
        await props.api.delete(`/plugin/ClashRuleProvider/proxies/${n}/patch`);
        emit("refresh", ["proxies", "clash-outbounds"]);
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", err.message || "删除补丁失败");
        }
      } finally {
        loading.value = false;
      }
    }
    async function handleStatusChange(name, disabled) {
      loading.value = true;
      try {
        const proxy = props.proxies.find((p) => p.data.name === name);
        if (!proxy) {
          emit("show-error", "Proxy not found");
          return;
        }
        const n = encodeURIComponent(name);
        const newMeta = { ...proxy.meta, disabled };
        await props.api.patch(`/plugin/ClashRuleProvider/proxies/${n}/meta`, newMeta);
        emit("refresh", ["proxies", "clash-outbounds"]);
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", err.message || "更新代理状态失败");
        }
      } finally {
        loading.value = false;
      }
    }
    function editVisibility(name) {
      const proxy = props.proxies.find((p) => p.data.name === name);
      if (!proxy) {
        emit("show-error", "Proxy not found");
        return;
      }
      const n = encodeURIComponent(name);
      emit("edit-visibility", proxy.meta, `/plugin/ClashRuleProvider/proxies/${n}/meta`, "proxies");
    }
    return (_ctx, _cache) => {
      const _component_v_progress_circular = _resolveComponent$d("v-progress-circular");
      const _component_v_overlay = _resolveComponent$d("v-overlay");
      const _component_v_text_field = _resolveComponent$d("v-text-field");
      const _component_v_col = _resolveComponent$d("v-col");
      const _component_v_btn = _resolveComponent$d("v-btn");
      const _component_v_btn_group = _resolveComponent$d("v-btn-group");
      const _component_v_row = _resolveComponent$d("v-row");
      const _component_v_pagination = _resolveComponent$d("v-pagination");
      const _component_v_list_item_title = _resolveComponent$d("v-list-item-title");
      const _component_v_list_item = _resolveComponent$d("v-list-item");
      const _component_v_list = _resolveComponent$d("v-list");
      const _component_v_menu = _resolveComponent$d("v-menu");
      const _component_v_divider = _resolveComponent$d("v-divider");
      const _component_v_card_title = _resolveComponent$d("v-card-title");
      const _component_v_select = _resolveComponent$d("v-select");
      const _component_v_textarea = _resolveComponent$d("v-textarea");
      const _component_v_alert = _resolveComponent$d("v-alert");
      const _component_v_card_text = _resolveComponent$d("v-card-text");
      const _component_v_spacer = _resolveComponent$d("v-spacer");
      const _component_v_card_actions = _resolveComponent$d("v-card-actions");
      const _component_v_card = _resolveComponent$d("v-card");
      const _component_v_dialog = _resolveComponent$d("v-dialog");
      return _openBlock$d(), _createElementBlock$6("div", _hoisted_1$9, [
        _createVNode$d(_component_v_overlay, {
          modelValue: loading.value,
          "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => loading.value = $event),
          contained: "",
          class: "align-center justify-center"
        }, {
          default: _withCtx$d(() => [
            _createVNode$d(_component_v_progress_circular, {
              indeterminate: "",
              color: "primary"
            })
          ]),
          _: 1
        }, 8, ["modelValue"]),
        _createElementVNode$a("div", _hoisted_2$7, [
          _createVNode$d(_component_v_row, {
            align: "center",
            "no-gutters": ""
          }, {
            default: _withCtx$d(() => [
              _createVNode$d(_component_v_col, {
                cols: "10",
                sm: "6",
                class: "d-flex justify-start"
              }, {
                default: _withCtx$d(() => [
                  _createVNode$d(_component_v_text_field, {
                    modelValue: searchProxies.value,
                    "onUpdate:modelValue": _cache[1] || (_cache[1] = ($event) => searchProxies.value = $event),
                    label: "搜索出站代理",
                    clearable: "",
                    density: "compact",
                    variant: "solo-filled",
                    "hide-details": "",
                    class: "search-field",
                    "prepend-inner-icon": "mdi-magnify",
                    flat: "",
                    rounded: "pill",
                    "single-line": "",
                    disabled: loading.value
                  }, null, 8, ["modelValue", "disabled"])
                ]),
                _: 1
              }),
              _createVNode$d(_component_v_col, {
                cols: "2",
                sm: "6",
                class: "d-flex justify-end"
              }, {
                default: _withCtx$d(() => [
                  _createVNode$d(_component_v_btn_group, {
                    variant: "outlined",
                    rounded: ""
                  }, {
                    default: _withCtx$d(() => [
                      _createVNode$d(_component_v_btn, {
                        icon: "mdi-import",
                        disabled: loading.value,
                        onClick: openImportProxiesDialog
                      }, null, 8, ["disabled"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _createElementVNode$a("div", _hoisted_3$7, [
          _createVNode$d(_sfc_main$g, {
            "items-per-page": itemsPerPageProxies.value,
            page: pageProxies.value,
            proxies: _ctx.proxies,
            onCopyToClipboard: _cache[2] || (_cache[2] = (t) => emit("copy-to-clipboard", t)),
            onShowYaml: _cache[3] || (_cache[3] = (o) => emit("show-yaml", o)),
            onEditProxy: openProxiesDialog,
            onDeleteProxy: deleteProxy,
            onDeletePatch: deletePatch,
            onChangeStatus: handleStatusChange,
            onEditVisibility: editVisibility
          }, null, 8, ["items-per-page", "page", "proxies"])
        ]),
        _createElementVNode$a("div", _hoisted_4$7, [
          _createVNode$d(_component_v_row, null, {
            default: _withCtx$d(() => [
              (_openBlock$d(true), _createElementBlock$6(_Fragment$6, null, _renderList$6(paginatedExtraProxies.value, (item) => {
                return _openBlock$d(), _createBlock$d(_component_v_col, {
                  key: item.data.name,
                  cols: "12"
                }, {
                  default: _withCtx$d(() => [
                    _createVNode$d(ProxyCard, {
                      "proxy-data": item,
                      onCopyToClipboard: _cache[4] || (_cache[4] = (t) => emit("copy-to-clipboard", t)),
                      onShowYaml: _cache[5] || (_cache[5] = (o) => emit("show-yaml", o)),
                      onEditProxy: openProxiesDialog,
                      onDeleteProxy: deleteProxy,
                      onDeletePatch: deletePatch,
                      onChangeStatus: handleStatusChange,
                      onEditVisibility: editVisibility
                    }, null, 8, ["proxy-data"])
                  ]),
                  _: 2
                }, 1024);
              }), 128))
            ]),
            _: 1
          })
        ]),
        _createElementVNode$a("div", _hoisted_5$4, [
          _createVNode$d(_component_v_row, {
            align: "center",
            "no-gutters": ""
          }, {
            default: _withCtx$d(() => [
              _createVNode$d(_component_v_col, {
                cols: "2",
                md: "1"
              }),
              _createVNode$d(_component_v_col, {
                cols: "8",
                md: "10",
                class: "d-flex justify-center"
              }, {
                default: _withCtx$d(() => [
                  _createVNode$d(_component_v_pagination, {
                    modelValue: pageProxies.value,
                    "onUpdate:modelValue": _cache[6] || (_cache[6] = ($event) => pageProxies.value = $event),
                    length: pageCountProxies.value,
                    "total-visible": "5",
                    class: "d-none d-sm-flex my-0",
                    rounded: "circle",
                    disabled: loading.value
                  }, null, 8, ["modelValue", "length", "disabled"]),
                  _createVNode$d(_component_v_pagination, {
                    modelValue: pageProxies.value,
                    "onUpdate:modelValue": _cache[7] || (_cache[7] = ($event) => pageProxies.value = $event),
                    length: pageCountProxies.value,
                    "total-visible": "0",
                    class: "d-sm-none my-0",
                    rounded: "circle",
                    disabled: loading.value
                  }, null, 8, ["modelValue", "length", "disabled"])
                ]),
                _: 1
              }),
              _createVNode$d(_component_v_col, {
                cols: "2",
                md: "1",
                class: "d-flex justify-end"
              }, {
                default: _withCtx$d(() => [
                  _createVNode$d(_component_v_menu, null, {
                    activator: _withCtx$d(({ props: props2 }) => [
                      _createVNode$d(_component_v_btn, _mergeProps$a(props2, {
                        icon: "",
                        rounded: "circle",
                        variant: "tonal",
                        disabled: loading.value
                      }), {
                        default: _withCtx$d(() => [
                          _createTextVNode$d(_toDisplayString$c(_unref$b(pageTitle)(itemsPerPageProxies.value)), 1)
                        ]),
                        _: 2
                      }, 1040, ["disabled"])
                    ]),
                    default: _withCtx$d(() => [
                      _createVNode$d(_component_v_list, null, {
                        default: _withCtx$d(() => [
                          (_openBlock$d(true), _createElementBlock$6(_Fragment$6, null, _renderList$6(_unref$b(itemsPerPageOptions), (item, index) => {
                            return _openBlock$d(), _createBlock$d(_component_v_list_item, {
                              key: index,
                              value: item.value,
                              onClick: ($event) => itemsPerPageProxies.value = item.value
                            }, {
                              default: _withCtx$d(() => [
                                _createVNode$d(_component_v_list_item_title, null, {
                                  default: _withCtx$d(() => [
                                    _createTextVNode$d(_toDisplayString$c(item.title), 1)
                                  ]),
                                  _: 2
                                }, 1024)
                              ]),
                              _: 2
                            }, 1032, ["value", "onClick"]);
                          }), 128))
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _createVNode$d(_component_v_divider),
        _createVNode$d(_component_v_dialog, {
          modelValue: importExtraProxiesDialog.value,
          "onUpdate:modelValue": _cache[12] || (_cache[12] = ($event) => importExtraProxiesDialog.value = $event),
          "max-width": "40rem"
        }, {
          default: _withCtx$d(() => [
            _createVNode$d(_component_v_card, null, {
              default: _withCtx$d(() => [
                _createVNode$d(_component_v_card_title, null, {
                  default: _withCtx$d(() => _cache[17] || (_cache[17] = [
                    _createTextVNode$d("导入节点")
                  ])),
                  _: 1
                }),
                _createVNode$d(_component_v_card_text, { style: { "max-height": "900px", "overflow-y": "auto" } }, {
                  default: _withCtx$d(() => [
                    _createVNode$d(_component_v_select, {
                      modelValue: importProxies.value.type,
                      "onUpdate:modelValue": _cache[8] || (_cache[8] = ($event) => importProxies.value.type = $event),
                      items: importProxiesTypes,
                      label: "内容格式",
                      required: "",
                      class: "mb-4"
                    }, null, 8, ["modelValue"]),
                    importProxies.value.type === "YAML" ? (_openBlock$d(), _createBlock$d(_unref$b(VAceEditor), {
                      key: 0,
                      value: importProxies.value.payload,
                      "onUpdate:value": _cache[9] || (_cache[9] = ($event) => importProxies.value.payload = $event),
                      lang: "yaml",
                      theme: "monokai",
                      options: editorOptions,
                      placeholder: proxiesPlaceholder.value,
                      style: { "height": "30rem", "width": "100%", "margin-bottom": "16px" }
                    }, null, 8, ["value", "placeholder"])) : (_openBlock$d(), _createBlock$d(_component_v_textarea, {
                      key: 1,
                      modelValue: importProxies.value.payload,
                      "onUpdate:modelValue": _cache[10] || (_cache[10] = ($event) => importProxies.value.payload = $event),
                      label: "内容",
                      required: "",
                      placeholder: importExtraProxiesPlaceholderText.value,
                      class: "mb-4",
                      rows: "4",
                      "auto-grow": ""
                    }, null, 8, ["modelValue", "placeholder"])),
                    importProxies.value.type === "YAML" ? (_openBlock$d(), _createBlock$d(_component_v_alert, {
                      key: 2,
                      type: "info",
                      dense: "",
                      variant: "tonal"
                    }, {
                      default: _withCtx$d(() => _cache[18] || (_cache[18] = [
                        _createTextVNode$d(" 请输入 Clash 规则中的 "),
                        _createElementVNode$a("strong", null, "proxies", -1),
                        _createTextVNode$d(" 字段，例如："),
                        _createElementVNode$a("br", null, null, -1),
                        _createElementVNode$a("pre", { style: { "white-space": "pre-wrap", "font-family": "monospace", "margin": "0" } }, [
                          _createTextVNode$d(""),
                          _createElementVNode$a("code", null, 'proxies:\n  - name: "ss node"\n    type: "ss"')
                        ], -1)
                      ])),
                      _: 1
                    })) : _createCommentVNode$a("", true),
                    importProxies.value.type === "LINK" ? (_openBlock$d(), _createBlock$d(_component_v_alert, {
                      key: 3,
                      type: "info",
                      dense: "",
                      variant: "tonal"
                    }, {
                      default: _withCtx$d(() => _cache[19] || (_cache[19] = [
                        _createTextVNode$d(" 请输入 V2RayN 格式的分享链接，例如："),
                        _createElementVNode$a("br", null, null, -1),
                        _createElementVNode$a("code", null, "vmess://xxxx", -1),
                        _createElementVNode$a("br", null, null, -1),
                        _createElementVNode$a("code", null, "ss://xxxx", -1)
                      ])),
                      _: 1
                    })) : _createCommentVNode$a("", true)
                  ]),
                  _: 1
                }),
                _createVNode$d(_component_v_card_actions, null, {
                  default: _withCtx$d(() => [
                    _createVNode$d(_component_v_spacer),
                    _createVNode$d(_component_v_btn, {
                      color: "secondary",
                      onClick: _cache[11] || (_cache[11] = ($event) => importExtraProxiesDialog.value = false)
                    }, {
                      default: _withCtx$d(() => _cache[20] || (_cache[20] = [
                        _createTextVNode$d("取消")
                      ])),
                      _: 1
                    }),
                    _createVNode$d(_component_v_btn, {
                      color: "primary",
                      loading: importProxiesLoading.value,
                      onClick: importExtraProxies
                    }, {
                      default: _withCtx$d(() => _cache[21] || (_cache[21] = [
                        _createTextVNode$d(" 导入 ")
                      ])),
                      _: 1
                    }, 8, ["loading"])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        }, 8, ["modelValue"]),
        proxiesDialogVisible.value ? (_openBlock$d(), _createBlock$d(_sfc_main$e, {
          key: 0,
          modelValue: proxiesDialogVisible.value,
          "onUpdate:modelValue": _cache[13] || (_cache[13] = ($event) => proxiesDialogVisible.value = $event),
          "proxy-data": editingProxy.value,
          api: _ctx.api,
          onRefresh: _cache[14] || (_cache[14] = ($event) => emit("refresh", ["proxies"])),
          onClose: closeProxyDialog,
          onShowSnackbar: _cache[15] || (_cache[15] = (val) => emit("show-snackbar", val)),
          onShowError: _cache[16] || (_cache[16] = (msg) => emit("show-error", msg))
        }, null, 8, ["modelValue", "proxy-data", "api"])) : _createCommentVNode$a("", true)
      ]);
    };
  }
});

const {defineComponent:_defineComponent$c} = await importShared('vue');

const {createTextVNode:_createTextVNode$c,resolveComponent:_resolveComponent$c,withCtx:_withCtx$c,createVNode:_createVNode$c,unref:_unref$a,toDisplayString:_toDisplayString$b,createElementVNode:_createElementVNode$9,openBlock:_openBlock$c,createBlock:_createBlock$c,createCommentVNode:_createCommentVNode$9} = await importShared('vue');

const _hoisted_1$8 = { class: "card-header pa-4" };
const _hoisted_2$6 = { class: "d-flex align-center overflow-hidden" };
const _hoisted_3$6 = { class: "d-flex flex-column overflow-hidden" };
const _hoisted_4$6 = { class: "text-subtitle-1 font-weight-bold text-truncate" };
const _hoisted_5$3 = { class: "text-caption text-medium-emphasis text-truncate" };
const _hoisted_6$1 = {
  class: "d-flex flex-wrap gap-2 mb-4",
  style: { "gap": "8px" }
};
const _hoisted_7$1 = { class: "stats-grid mb-4" };
const _hoisted_8$1 = { class: "stat-item" };
const _hoisted_9 = { class: "text-body-2 font-weight-bold" };
const _hoisted_10 = { class: "stat-item text-right" };
const _hoisted_11 = { class: "text-body-2 font-weight-bold" };
const _hoisted_12 = { class: "d-flex justify-space-between text-caption text-medium-emphasis" };
const _hoisted_13 = { class: "card-actions px-4 py-2 d-flex align-center bg-surface-variant-lighten" };
const _hoisted_14 = { class: "d-flex align-center" };
const {ref: ref$8} = await importShared('vue');

const _sfc_main$c = /* @__PURE__ */ _defineComponent$c({
  __name: "SubscriptionCard",
  props: {
    info: {},
    url: {},
    api: {}
  },
  emits: ["show-error", "show-snackbar", "refresh", "copy-to-clipboard", "start-loading", "end-loading"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const loading = ref$8(false);
    async function updateSubscription() {
      loading.value = true;
      emit("start-loading");
      try {
        await props.api.put("plugin/ClashRuleProvider/refresh", {
          url: props.url
        });
        emit("show-snackbar", {
          show: true,
          message: "订阅更新成功",
          color: "success"
        });
        emit("refresh", [
          "status",
          "clash-outbounds",
          "rule-providers",
          "proxy-groups",
          "proxies",
          "proxy-providers"
        ]);
      } catch (err) {
        if (err instanceof Error) emit("show-error", "订阅更新失败: " + (err.message || "未知错误"));
      } finally {
        loading.value = false;
        emit("end-loading");
      }
    }
    async function toggleSubscription(val) {
      emit("start-loading");
      try {
        await props.api.post("plugin/ClashRuleProvider/subscription-info", {
          url: props.url,
          enabled: val
        });
        emit("show-snackbar", {
          show: true,
          message: "设置成功",
          color: "success"
        });
        emit("refresh", ["status"]);
      } catch (err) {
        if (err instanceof Error) emit("show-error", "设置自动更新失败: " + (err.message || "未知错误"));
        emit("refresh", ["status"]);
      } finally {
        emit("end-loading");
      }
    }
    return (_ctx, _cache) => {
      const _component_v_icon = _resolveComponent$c("v-icon");
      const _component_v_avatar = _resolveComponent$c("v-avatar");
      const _component_v_spacer = _resolveComponent$c("v-spacer");
      const _component_v_divider = _resolveComponent$c("v-divider");
      const _component_v_chip = _resolveComponent$c("v-chip");
      const _component_v_progress_linear = _resolveComponent$c("v-progress-linear");
      const _component_v_card_text = _resolveComponent$c("v-card-text");
      const _component_v_tooltip = _resolveComponent$c("v-tooltip");
      const _component_v_btn = _resolveComponent$c("v-btn");
      const _component_v_switch = _resolveComponent$c("v-switch");
      const _component_v_card = _resolveComponent$c("v-card");
      return _openBlock$c(), _createBlock$c(_component_v_card, {
        class: "subscription-card mb-4",
        elevation: "0",
        border: ""
      }, {
        default: _withCtx$c(() => [
          _createElementVNode$9("div", _hoisted_1$8, [
            _createElementVNode$9("div", _hoisted_2$6, [
              _createVNode$c(_component_v_avatar, {
                color: "primary",
                variant: "tonal",
                rounded: "lg",
                class: "mr-3"
              }, {
                default: _withCtx$c(() => [
                  _createVNode$c(_component_v_icon, null, {
                    default: _withCtx$c(() => _cache[0] || (_cache[0] = [
                      _createTextVNode$c("mdi-rss")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              }),
              _createElementVNode$9("div", _hoisted_3$6, [
                _createElementVNode$9("div", _hoisted_4$6, _toDisplayString$b(_unref$a(extractDomain)(_ctx.url)), 1),
                _createElementVNode$9("div", _hoisted_5$3, _toDisplayString$b(_ctx.url), 1)
              ])
            ]),
            _createVNode$c(_component_v_spacer)
          ]),
          _createVNode$c(_component_v_divider),
          _createVNode$c(_component_v_card_text, { class: "pa-4" }, {
            default: _withCtx$c(() => [
              _createElementVNode$9("div", _hoisted_6$1, [
                _ctx.info.proxy_num != null ? (_openBlock$c(), _createBlock$c(_component_v_chip, {
                  key: 0,
                  size: "small",
                  color: "primary",
                  variant: "flat",
                  class: "font-weight-medium"
                }, {
                  default: _withCtx$c(() => [
                    _createVNode$c(_component_v_icon, {
                      start: "",
                      size: "small"
                    }, {
                      default: _withCtx$c(() => _cache[1] || (_cache[1] = [
                        _createTextVNode$c("mdi-server-network")
                      ])),
                      _: 1
                    }),
                    _createTextVNode$c(" " + _toDisplayString$b(_ctx.info.proxy_num) + " 节点 ", 1)
                  ]),
                  _: 1
                })) : _createCommentVNode$9("", true),
                _ctx.info.last_update ? (_openBlock$c(), _createBlock$c(_component_v_chip, {
                  key: 1,
                  size: "small",
                  color: "secondary",
                  variant: "tonal"
                }, {
                  default: _withCtx$c(() => [
                    _createVNode$c(_component_v_icon, {
                      start: "",
                      size: "small"
                    }, {
                      default: _withCtx$c(() => _cache[2] || (_cache[2] = [
                        _createTextVNode$c("mdi-clock-outline")
                      ])),
                      _: 1
                    }),
                    _createTextVNode$c(" " + _toDisplayString$b(_unref$a(formatTimestamp)(_ctx.info.last_update)), 1)
                  ]),
                  _: 1
                })) : _createCommentVNode$9("", true),
                _ctx.info.expire ? (_openBlock$c(), _createBlock$c(_component_v_chip, {
                  key: 2,
                  size: "small",
                  color: _unref$a(getExpireColor)(_ctx.info.expire),
                  variant: "tonal"
                }, {
                  default: _withCtx$c(() => [
                    _createVNode$c(_component_v_icon, {
                      start: "",
                      size: "small"
                    }, {
                      default: _withCtx$c(() => _cache[3] || (_cache[3] = [
                        _createTextVNode$c("mdi-calendar-clock")
                      ])),
                      _: 1
                    }),
                    _createTextVNode$c(" 到期：" + _toDisplayString$b(_unref$a(formatTimestamp)(_ctx.info.expire)), 1)
                  ]),
                  _: 1
                }, 8, ["color"])) : _createCommentVNode$9("", true)
              ]),
              _createElementVNode$9("div", _hoisted_7$1, [
                _createElementVNode$9("div", _hoisted_8$1, [
                  _cache[4] || (_cache[4] = _createElementVNode$9("div", { class: "text-caption text-medium-emphasis" }, "已用", -1)),
                  _createElementVNode$9("div", _hoisted_9, _toDisplayString$b(_unref$a(formatBytes)(_ctx.info.download + _ctx.info.upload)), 1)
                ]),
                _createElementVNode$9("div", _hoisted_10, [
                  _cache[5] || (_cache[5] = _createElementVNode$9("div", { class: "text-caption text-medium-emphasis" }, "剩余", -1)),
                  _createElementVNode$9("div", _hoisted_11, _toDisplayString$b(_unref$a(formatBytes)(_ctx.info.total - _ctx.info.download - _ctx.info.upload)), 1)
                ])
              ]),
              _createVNode$c(_component_v_progress_linear, {
                "model-value": _unref$a(getUsedPercentageFloor)(_ctx.info),
                color: _unref$a(getUsageColor)(_unref$a(getUsedPercentageFloor)(_ctx.info)),
                height: "8",
                rounded: "",
                class: "mb-2"
              }, null, 8, ["model-value", "color"]),
              _createElementVNode$9("div", _hoisted_12, [
                _createElementVNode$9("span", null, "↓ " + _toDisplayString$b(_unref$a(formatBytes)(_ctx.info.download)), 1),
                _createElementVNode$9("span", null, "↑ " + _toDisplayString$b(_unref$a(formatBytes)(_ctx.info.upload)), 1),
                _createElementVNode$9("span", null, "Total: " + _toDisplayString$b(_unref$a(formatBytes)(_ctx.info.total)), 1)
              ])
            ]),
            _: 1
          }),
          _createVNode$c(_component_v_divider),
          _createElementVNode$9("div", _hoisted_13, [
            _createVNode$c(_component_v_btn, {
              icon: "",
              size: "small",
              variant: "text",
              color: "primary",
              loading: loading.value,
              onClick: updateSubscription
            }, {
              default: _withCtx$c(() => [
                _createVNode$c(_component_v_icon, null, {
                  default: _withCtx$c(() => _cache[6] || (_cache[6] = [
                    _createTextVNode$c("mdi-refresh")
                  ])),
                  _: 1
                }),
                _createVNode$c(_component_v_tooltip, {
                  activator: "parent",
                  location: "top"
                }, {
                  default: _withCtx$c(() => _cache[7] || (_cache[7] = [
                    _createTextVNode$c("刷新")
                  ])),
                  _: 1
                })
              ]),
              _: 1
            }, 8, ["loading"]),
            _createVNode$c(_component_v_spacer),
            _createElementVNode$9("div", _hoisted_14, [
              _cache[8] || (_cache[8] = _createElementVNode$9("span", { class: "text-caption mr-2 text-medium-emphasis" }, "自动更新", -1)),
              _createVNode$c(_component_v_switch, {
                "model-value": _ctx.info.enabled,
                "hide-details": "",
                density: "compact",
                color: "primary",
                inset: "",
                "onUpdate:modelValue": toggleSubscription
              }, null, 8, ["model-value"])
            ])
          ])
        ]),
        _: 1
      });
    };
  }
});

const SubscriptionCard = /* @__PURE__ */ _export_sfc(_sfc_main$c, [["__scopeId", "data-v-97c0f367"]]);

const {defineComponent:_defineComponent$b} = await importShared('vue');

const {resolveComponent:_resolveComponent$b,createVNode:_createVNode$b,withCtx:_withCtx$b,createTextVNode:_createTextVNode$b,createElementVNode:_createElementVNode$8,openBlock:_openBlock$b,createBlock:_createBlock$b,createCommentVNode:_createCommentVNode$8,renderList:_renderList$5,Fragment:_Fragment$5,createElementBlock:_createElementBlock$5} = await importShared('vue');

const _hoisted_1$7 = { class: "mb-2 position-relative" };
const {ref: ref$7} = await importShared('vue');

const _sfc_main$b = /* @__PURE__ */ _defineComponent$b({
  __name: "SubscriptionTab",
  props: {
    subscriptionsInfo: {},
    api: {}
  },
  emits: ["show-error", "show-snackbar", "refresh", "copy-to-clipboard", "switch"],
  setup(__props, { emit: __emit }) {
    const emit = __emit;
    const loading = ref$7(false);
    return (_ctx, _cache) => {
      const _component_v_progress_circular = _resolveComponent$b("v-progress-circular");
      const _component_v_overlay = _resolveComponent$b("v-overlay");
      const _component_v_icon = _resolveComponent$b("v-icon");
      const _component_v_btn = _resolveComponent$b("v-btn");
      const _component_v_card_text = _resolveComponent$b("v-card-text");
      const _component_v_card = _resolveComponent$b("v-card");
      const _component_v_row = _resolveComponent$b("v-row");
      const _component_v_col = _resolveComponent$b("v-col");
      return _openBlock$b(), _createElementBlock$5("div", _hoisted_1$7, [
        _createVNode$b(_component_v_overlay, {
          modelValue: loading.value,
          "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => loading.value = $event),
          contained: "",
          class: "align-center justify-center"
        }, {
          default: _withCtx$b(() => [
            _createVNode$b(_component_v_progress_circular, {
              indeterminate: "",
              color: "primary"
            })
          ]),
          _: 1
        }, 8, ["modelValue"]),
        Object.keys(_ctx.subscriptionsInfo).length === 0 ? (_openBlock$b(), _createBlock$b(_component_v_row, {
          key: 0,
          class: "pa-6 justify-center"
        }, {
          default: _withCtx$b(() => [
            _createVNode$b(_component_v_card, {
              class: "mx-auto text-center py-8 px-4",
              "max-width": "400",
              elevation: "10",
              rounded: "xl",
              style: { "background": "linear-gradient(135deg, #d6c355 0%, #fda085 100%)" }
            }, {
              default: _withCtx$b(() => [
                _createVNode$b(_component_v_card_text, { class: "d-flex flex-column align-center" }, {
                  default: _withCtx$b(() => [
                    _createVNode$b(_component_v_icon, {
                      size: "64",
                      color: "white",
                      class: "mb-4 bounce"
                    }, {
                      default: _withCtx$b(() => _cache[8] || (_cache[8] = [
                        _createTextVNode$b(" mdi-emoticon-happy-outline ")
                      ])),
                      _: 1
                    }),
                    _cache[10] || (_cache[10] = _createElementVNode$8("h2", { class: "text-h6 font-weight-bold white--text mb-2" }, "还没有订阅呢 🎉", -1)),
                    _cache[11] || (_cache[11] = _createElementVNode$8("p", { class: "white--text mb-4" }, "试试添加一个订阅吧！", -1)),
                    _createVNode$b(_component_v_btn, {
                      color: "info",
                      dark: "",
                      rounded: "",
                      elevation: "6",
                      onClick: _cache[1] || (_cache[1] = ($event) => emit("switch"))
                    }, {
                      default: _withCtx$b(() => _cache[9] || (_cache[9] = [
                        _createTextVNode$b(" 去配置 🚀 ")
                      ])),
                      _: 1
                    })
                  ]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _: 1
        })) : _createCommentVNode$8("", true),
        _createVNode$b(_component_v_row, { class: "pa-4" }, {
          default: _withCtx$b(() => [
            (_openBlock$b(true), _createElementBlock$5(_Fragment$5, null, _renderList$5(_ctx.subscriptionsInfo, (info, url) => {
              return _openBlock$b(), _createBlock$b(_component_v_col, {
                key: url,
                cols: "12",
                md: "6"
              }, {
                default: _withCtx$b(() => [
                  _createVNode$b(SubscriptionCard, {
                    info,
                    url: String(url),
                    api: _ctx.api,
                    onRefresh: _cache[2] || (_cache[2] = (r) => emit("refresh", r)),
                    onShowSnackbar: _cache[3] || (_cache[3] = (val) => emit("show-snackbar", val)),
                    onShowError: _cache[4] || (_cache[4] = (msg) => emit("show-error", msg)),
                    onCopyToClipboard: _cache[5] || (_cache[5] = (t) => emit("copy-to-clipboard", t)),
                    onStartLoading: _cache[6] || (_cache[6] = ($event) => loading.value = true),
                    onEndLoading: _cache[7] || (_cache[7] = ($event) => loading.value = false)
                  }, null, 8, ["info", "url", "api"])
                ]),
                _: 2
              }, 1024);
            }), 128))
          ]),
          _: 1
        })
      ]);
    };
  }
});

const SubscriptionTab = /* @__PURE__ */ _export_sfc(_sfc_main$b, [["__scopeId", "data-v-6a1d5a83"]]);

const {defineComponent:_defineComponent$a} = await importShared('vue');

const {createTextVNode:_createTextVNode$a,resolveComponent:_resolveComponent$a,withCtx:_withCtx$a,createVNode:_createVNode$a,mergeProps:_mergeProps$9,unref:_unref$9,toDisplayString:_toDisplayString$a,openBlock:_openBlock$a,createBlock:_createBlock$a,createCommentVNode:_createCommentVNode$7} = await importShared('vue');
const _sfc_main$a = /* @__PURE__ */ _defineComponent$a({
  __name: "RuleProviderActionMenu",
  props: {
    ruleProvider: {
      type: Object,
      required: true
    }
  },
  emits: ["showYaml", "edit", "delete", "changeStatus", "editVisibility"],
  setup(__props, { emit: __emit }) {
    const emit = __emit;
    return (_ctx, _cache) => {
      const _component_v_icon = _resolveComponent$a("v-icon");
      const _component_v_btn = _resolveComponent$a("v-btn");
      const _component_v_list_item_title = _resolveComponent$a("v-list-item-title");
      const _component_v_list_item = _resolveComponent$a("v-list-item");
      const _component_v_list = _resolveComponent$a("v-list");
      const _component_v_menu = _resolveComponent$a("v-menu");
      return _openBlock$a(), _createBlock$a(_component_v_menu, { "min-width": "120" }, {
        activator: _withCtx$a(({ props }) => [
          _createVNode$a(_component_v_btn, _mergeProps$9({
            color: "secondary",
            icon: "",
            size: "small",
            variant: "text"
          }, props), {
            default: _withCtx$a(() => [
              _createVNode$a(_component_v_icon, null, {
                default: _withCtx$a(() => _cache[5] || (_cache[5] = [
                  _createTextVNode$a("mdi-dots-vertical")
                ])),
                _: 1
              })
            ]),
            _: 2
          }, 1040)
        ]),
        default: _withCtx$a(() => [
          _createVNode$a(_component_v_list, { density: "compact" }, {
            default: _withCtx$a(() => [
              _unref$9(isManual)(__props.ruleProvider.meta.source) ? (_openBlock$a(), _createBlock$a(_component_v_list_item, {
                key: 0,
                onClick: _cache[0] || (_cache[0] = ($event) => emit("changeStatus", !__props.ruleProvider.meta.disabled))
              }, {
                prepend: _withCtx$a(() => [
                  _createVNode$a(_component_v_icon, {
                    size: "small",
                    color: __props.ruleProvider.meta.disabled ? "success" : "grey"
                  }, {
                    default: _withCtx$a(() => [
                      _createTextVNode$a(_toDisplayString$a(__props.ruleProvider.meta.disabled ? "mdi-play-circle-outline" : "mdi-stop-circle-outline"), 1)
                    ]),
                    _: 1
                  }, 8, ["color"])
                ]),
                default: _withCtx$a(() => [
                  _createVNode$a(_component_v_list_item_title, null, {
                    default: _withCtx$a(() => [
                      _createTextVNode$a(_toDisplayString$a(__props.ruleProvider.meta.disabled ? "启用" : "禁用"), 1)
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })) : _createCommentVNode$7("", true),
              _unref$9(isManual)(__props.ruleProvider.meta.source) ? (_openBlock$a(), _createBlock$a(_component_v_list_item, {
                key: 1,
                onClick: _cache[1] || (_cache[1] = ($event) => emit("edit"))
              }, {
                prepend: _withCtx$a(() => [
                  _createVNode$a(_component_v_icon, {
                    size: "small",
                    color: "primary"
                  }, {
                    default: _withCtx$a(() => _cache[6] || (_cache[6] = [
                      _createTextVNode$a("mdi-file-edit-outline")
                    ])),
                    _: 1
                  })
                ]),
                default: _withCtx$a(() => [
                  _createVNode$a(_component_v_list_item_title, null, {
                    default: _withCtx$a(() => _cache[7] || (_cache[7] = [
                      _createTextVNode$a("编辑")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              })) : _createCommentVNode$7("", true),
              _createVNode$a(_component_v_list_item, {
                onClick: _cache[2] || (_cache[2] = ($event) => emit("showYaml"))
              }, {
                prepend: _withCtx$a(() => [
                  _createVNode$a(_component_v_icon, {
                    size: "small",
                    color: "info"
                  }, {
                    default: _withCtx$a(() => _cache[8] || (_cache[8] = [
                      _createTextVNode$a("mdi-code-json")
                    ])),
                    _: 1
                  })
                ]),
                default: _withCtx$a(() => [
                  _createVNode$a(_component_v_list_item_title, null, {
                    default: _withCtx$a(() => _cache[9] || (_cache[9] = [
                      _createTextVNode$a("查看")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              }),
              _unref$9(isManual)(__props.ruleProvider.meta.source) ? (_openBlock$a(), _createBlock$a(_component_v_list_item, {
                key: 2,
                onClick: _cache[3] || (_cache[3] = ($event) => emit("editVisibility"))
              }, {
                prepend: _withCtx$a(() => [
                  _createVNode$a(_component_v_icon, {
                    size: "small",
                    color: "warning"
                  }, {
                    default: _withCtx$a(() => _cache[10] || (_cache[10] = [
                      _createTextVNode$a("mdi-eye-off-outline")
                    ])),
                    _: 1
                  })
                ]),
                default: _withCtx$a(() => [
                  _createVNode$a(_component_v_list_item_title, null, {
                    default: _withCtx$a(() => _cache[11] || (_cache[11] = [
                      _createTextVNode$a("隐藏")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              })) : _createCommentVNode$7("", true),
              _unref$9(isManual)(__props.ruleProvider.meta.source) ? (_openBlock$a(), _createBlock$a(_component_v_list_item, {
                key: 3,
                onClick: _cache[4] || (_cache[4] = ($event) => emit("delete"))
              }, {
                prepend: _withCtx$a(() => [
                  _createVNode$a(_component_v_icon, {
                    size: "small",
                    color: "error"
                  }, {
                    default: _withCtx$a(() => _cache[12] || (_cache[12] = [
                      _createTextVNode$a("mdi-trash-can-outline")
                    ])),
                    _: 1
                  })
                ]),
                default: _withCtx$a(() => [
                  _createVNode$a(_component_v_list_item_title, null, {
                    default: _withCtx$a(() => _cache[13] || (_cache[13] = [
                      _createTextVNode$a("删除")
                    ])),
                    _: 1
                  })
                ]),
                _: 1
              })) : _createCommentVNode$7("", true)
            ]),
            _: 1
          })
        ]),
        _: 1
      });
    };
  }
});

const {defineComponent:_defineComponent$9} = await importShared('vue');

const {unref:_unref$8,toDisplayString:_toDisplayString$9,createTextVNode:_createTextVNode$9,resolveComponent:_resolveComponent$9,withCtx:_withCtx$9,createVNode:_createVNode$9,openBlock:_openBlock$9,createBlock:_createBlock$9,createCommentVNode:_createCommentVNode$6,mergeProps:_mergeProps$8,createElementVNode:_createElementVNode$7} = await importShared('vue');

const _hoisted_1$6 = { class: "d-flex align-center" };
const {ref: ref$6} = await importShared('vue');
const _sfc_main$9 = /* @__PURE__ */ _defineComponent$9({
  __name: "RuleProvidersTable",
  props: {
    ruleProviders: {
      type: Array,
      required: true
    },
    page: {
      type: Number,
      required: true
    },
    itemsPerPage: {
      type: Number,
      required: true
    },
    search: String
  },
  emits: ["editRuleProvider", "deleteRuleProvider", "showYaml", "changeStatus", "editVisibility"],
  setup(__props, { emit: __emit }) {
    const emit = __emit;
    const headersRuleProviders = ref$6([
      { title: "名称", key: "name", sortable: true },
      { title: "类型", key: "type", sortable: true },
      { title: "行为", key: "behavior", sortable: false },
      { title: "格式", key: "format", sortable: false },
      { title: "来源", key: "source", sortable: false },
      { title: "", key: "status", sortable: false, width: "1rem" },
      { title: "", key: "actions", sortable: false, width: "1rem" }
    ]);
    return (_ctx, _cache) => {
      const _component_v_chip = _resolveComponent$9("v-chip");
      const _component_v_icon = _resolveComponent$9("v-icon");
      const _component_v_tooltip = _resolveComponent$9("v-tooltip");
      const _component_v_data_table = _resolveComponent$9("v-data-table");
      return _openBlock$9(), _createBlock$9(_component_v_data_table, {
        headers: headersRuleProviders.value,
        items: __props.ruleProviders,
        search: __props.search,
        page: __props.page,
        "items-per-page": __props.itemsPerPage,
        "items-per-page-options": _unref$8(itemsPerPageOptions),
        "item-key": "name",
        class: "px-4",
        density: "compact",
        "hide-default-footer": "",
        "fixed-header": ""
      }, {
        "item.name": _withCtx$9(({ item }) => [
          _createVNode$9(_component_v_chip, {
            size: "small",
            pill: "",
            color: "secondary"
          }, {
            default: _withCtx$9(() => [
              _createTextVNode$9(_toDisplayString$9(item.name), 1)
            ]),
            _: 2
          }, 1024)
        ]),
        "item.type": _withCtx$9(({ item }) => [
          _createVNode$9(_component_v_chip, {
            size: "small",
            label: "",
            variant: "tonal",
            color: "primary"
          }, {
            default: _withCtx$9(() => [
              _createTextVNode$9(_toDisplayString$9(item.data.type), 1)
            ]),
            _: 2
          }, 1024)
        ]),
        "item.behavior": _withCtx$9(({ item }) => [
          item.data?.behavior ? (_openBlock$9(), _createBlock$9(_component_v_chip, {
            key: 0,
            color: _unref$8(getBehaviorColor)(item.data.behavior),
            size: "small",
            label: "",
            variant: "tonal"
          }, {
            default: _withCtx$9(() => [
              _createTextVNode$9(_toDisplayString$9(item.data.behavior), 1)
            ]),
            _: 2
          }, 1032, ["color"])) : _createCommentVNode$6("", true)
        ]),
        "item.format": _withCtx$9(({ item }) => [
          _createVNode$9(_component_v_chip, {
            color: _unref$8(getFormatColor)(item.data.format),
            size: "small",
            label: "",
            variant: "tonal"
          }, {
            default: _withCtx$9(() => [
              _createTextVNode$9(_toDisplayString$9(item.data.format), 1)
            ]),
            _: 2
          }, 1032, ["color"])
        ]),
        "item.source": _withCtx$9(({ item }) => [
          _createVNode$9(_component_v_chip, {
            color: _unref$8(getSourceColor)(item.meta.source),
            size: "small",
            variant: "outlined"
          }, {
            default: _withCtx$9(() => [
              _createTextVNode$9(_toDisplayString$9(item.meta.source), 1)
            ]),
            _: 2
          }, 1032, ["color"])
        ]),
        "item.status": _withCtx$9(({ item }) => [
          _createElementVNode$7("div", _hoisted_1$6, [
            _createVNode$9(_component_v_icon, {
              color: item.meta.disabled ? "grey" : "success",
              class: "mr-1"
            }, {
              default: _withCtx$9(() => [
                _createTextVNode$9(_toDisplayString$9(item.meta.disabled ? "mdi-close-circle-outline" : "mdi-check-circle-outline"), 1)
              ]),
              _: 2
            }, 1032, ["color"]),
            item.meta.invisible_to && item.meta.invisible_to.length > 0 ? (_openBlock$9(), _createBlock$9(_component_v_tooltip, {
              key: 0,
              text: "已配置可见性限制",
              location: "top"
            }, {
              activator: _withCtx$9(({ props }) => [
                _createVNode$9(_component_v_icon, _mergeProps$8(props, {
                  size: "small",
                  color: "warning"
                }), {
                  default: _withCtx$9(() => _cache[0] || (_cache[0] = [
                    _createTextVNode$9(" mdi-eye-off-outline ")
                  ])),
                  _: 2
                }, 1040)
              ]),
              _: 1
            })) : _createCommentVNode$6("", true)
          ])
        ]),
        "item.actions": _withCtx$9(({ item }) => [
          _createVNode$9(_sfc_main$a, {
            "rule-provider": item,
            onChangeStatus: (disabled) => emit("changeStatus", item.name, disabled),
            onEdit: ($event) => emit("editRuleProvider", item.name),
            onShowYaml: ($event) => emit("showYaml", item.data),
            onDelete: ($event) => emit("deleteRuleProvider", item.name),
            onEditVisibility: ($event) => emit("editVisibility", item.name)
          }, null, 8, ["rule-provider", "onChangeStatus", "onEdit", "onShowYaml", "onDelete", "onEditVisibility"]),
          !_unref$8(isManual)(item.meta.source) ? (_openBlock$9(), _createBlock$9(_component_v_tooltip, {
            key: 0,
            activator: "parent",
            location: "top"
          }, {
            default: _withCtx$9(() => _cache[1] || (_cache[1] = [
              _createTextVNode$9(" 非手动添加 ")
            ])),
            _: 1
          })) : _createCommentVNode$6("", true)
        ]),
        _: 1
      }, 8, ["headers", "items", "search", "page", "items-per-page", "items-per-page-options"]);
    };
  }
});

const {defineComponent:_defineComponent$8} = await importShared('vue');

const {toDisplayString:_toDisplayString$8,createElementVNode:_createElementVNode$6,createTextVNode:_createTextVNode$8,resolveComponent:_resolveComponent$8,mergeProps:_mergeProps$7,withCtx:_withCtx$8,createVNode:_createVNode$8,openBlock:_openBlock$8,createBlock:_createBlock$8,createCommentVNode:_createCommentVNode$5,unref:_unref$7} = await importShared('vue');

const _hoisted_1$5 = { class: "d-flex justify-space-between align-center px-4 pt-3" };
const _hoisted_2$5 = ["title"];
const _hoisted_3$5 = { class: "d-flex align-center" };
const _hoisted_4$5 = { class: "text-body-2 font-weight-medium" };
const _sfc_main$8 = /* @__PURE__ */ _defineComponent$8({
  __name: "RuleProviderCard",
  props: {
    ruleProviderData: {
      type: Object,
      required: true
    }
  },
  emits: ["editRuleProvider", "deleteRuleProvider", "showYaml", "changeStatus", "editVisibility"],
  setup(__props, { emit: __emit }) {
    const emit = __emit;
    return (_ctx, _cache) => {
      const _component_v_icon = _resolveComponent$8("v-icon");
      const _component_v_tooltip = _resolveComponent$8("v-tooltip");
      const _component_v_chip = _resolveComponent$8("v-chip");
      const _component_v_col = _resolveComponent$8("v-col");
      const _component_v_row = _resolveComponent$8("v-row");
      const _component_v_card_text = _resolveComponent$8("v-card-text");
      const _component_v_divider = _resolveComponent$8("v-divider");
      const _component_v_spacer = _resolveComponent$8("v-spacer");
      const _component_v_card_actions = _resolveComponent$8("v-card-actions");
      const _component_v_card = _resolveComponent$8("v-card");
      return _openBlock$8(), _createBlock$8(_component_v_card, {
        rounded: "lg",
        elevation: "2",
        class: "rule-provider-card h-100 transition-swing",
        variant: "tonal"
      }, {
        default: _withCtx$8(() => [
          _createElementVNode$6("div", _hoisted_1$5, [
            _createElementVNode$6("span", {
              class: "font-weight-bold text-truncate",
              title: __props.ruleProviderData.name
            }, _toDisplayString$8(__props.ruleProviderData.name), 9, _hoisted_2$5),
            _createElementVNode$6("div", _hoisted_3$5, [
              __props.ruleProviderData.meta.invisible_to && __props.ruleProviderData.meta.invisible_to.length > 0 ? (_openBlock$8(), _createBlock$8(_component_v_tooltip, {
                key: 0,
                text: "已配置可见性限制",
                location: "top"
              }, {
                activator: _withCtx$8(({ props }) => [
                  _createVNode$8(_component_v_icon, _mergeProps$7(props, {
                    size: "small",
                    color: "warning",
                    class: "mr-2"
                  }), {
                    default: _withCtx$8(() => _cache[5] || (_cache[5] = [
                      _createTextVNode$8(" mdi-eye-off-outline ")
                    ])),
                    _: 2
                  }, 1040)
                ]),
                _: 1
              })) : _createCommentVNode$5("", true),
              _createVNode$8(_component_v_chip, {
                size: "small",
                color: _unref$7(getSourceColor)(__props.ruleProviderData.meta.source),
                variant: "outlined"
              }, {
                default: _withCtx$8(() => [
                  _createTextVNode$8(_toDisplayString$8(__props.ruleProviderData.meta.source), 1)
                ]),
                _: 1
              }, 8, ["color"])
            ])
          ]),
          _createVNode$8(_component_v_card_text, { class: "pt-2 pb-4" }, {
            default: _withCtx$8(() => [
              _createVNode$8(_component_v_row, {
                "no-gutters": "",
                class: "mb-2 align-center"
              }, {
                default: _withCtx$8(() => [
                  _createVNode$8(_component_v_col, {
                    cols: "3",
                    class: "text-caption text-medium-emphasis"
                  }, {
                    default: _withCtx$8(() => _cache[6] || (_cache[6] = [
                      _createTextVNode$8("类型")
                    ])),
                    _: 1
                  }),
                  _createVNode$8(_component_v_col, { cols: "9" }, {
                    default: _withCtx$8(() => [
                      _createElementVNode$6("span", _hoisted_4$5, _toDisplayString$8(__props.ruleProviderData.data.type), 1)
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode$8(_component_v_divider),
          _createVNode$8(_component_v_card_actions, null, {
            default: _withCtx$8(() => [
              _createVNode$8(_component_v_icon, {
                color: __props.ruleProviderData.meta.disabled ? "grey" : "success"
              }, {
                default: _withCtx$8(() => [
                  _createTextVNode$8(_toDisplayString$8(__props.ruleProviderData.meta.disabled ? "mdi-close-circle-outline" : "mdi-check-circle-outline"), 1)
                ]),
                _: 1
              }, 8, ["color"]),
              _createVNode$8(_component_v_spacer),
              _createVNode$8(_sfc_main$a, {
                "rule-provider": __props.ruleProviderData,
                onChangeStatus: _cache[0] || (_cache[0] = (disabled) => emit("changeStatus", __props.ruleProviderData.name, disabled)),
                onEdit: _cache[1] || (_cache[1] = ($event) => emit("editRuleProvider", __props.ruleProviderData.name)),
                onShowYaml: _cache[2] || (_cache[2] = ($event) => emit("showYaml", __props.ruleProviderData.data)),
                onDelete: _cache[3] || (_cache[3] = ($event) => emit("deleteRuleProvider", __props.ruleProviderData.name)),
                onEditVisibility: _cache[4] || (_cache[4] = ($event) => emit("editVisibility", __props.ruleProviderData.name))
              }, null, 8, ["rule-provider"])
            ]),
            _: 1
          })
        ]),
        _: 1
      });
    };
  }
});

const RuleProviderCard = /* @__PURE__ */ _export_sfc(_sfc_main$8, [["__scopeId", "data-v-01e2e8ef"]]);

const {defineComponent:_defineComponent$7} = await importShared('vue');

const {toDisplayString:_toDisplayString$7,createTextVNode:_createTextVNode$7,resolveComponent:_resolveComponent$7,withCtx:_withCtx$7,createVNode:_createVNode$7,unref:_unref$6,openBlock:_openBlock$7,createBlock:_createBlock$7,createCommentVNode:_createCommentVNode$4,mergeProps:_mergeProps$6,withModifiers:_withModifiers$1} = await importShared('vue');

const {ref: ref$5,toRaw: toRaw$3} = await importShared('vue');
const _sfc_main$7 = /* @__PURE__ */ _defineComponent$7({
  __name: "RuleProviderDialog",
  props: {
    initialValue: {
      type: Object,
      default: null
    },
    isAdding: {
      type: Boolean,
      default: true
    },
    api: {
      type: Object,
      required: true
    }
  },
  emits: ["close", "refresh", "show-snackbar", "show-error"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const ruleProviderTypes = ["http", "file", "inline"];
    const ruleProviderBehaviorTypes = ["domain", "ipcidr", "classical"];
    const ruleProviderFormatTypes = ["yaml", "text", "mrs"];
    const saveRuleProviderLoading = ref$5(false);
    const newRuleProvider = ref$5(
      props.initialValue ? structuredClone(toRaw$3(props.initialValue)) : {
        meta: { ...defaultMetadata },
        data: { ...defaultRuleProvider },
        name: ""
      }
    );
    const ruleProvidersForm = ref$5(null);
    async function saveRuleProvider() {
      if (!ruleProvidersForm.value) return;
      const { valid } = await ruleProvidersForm.value.validate();
      if (!valid) return;
      try {
        saveRuleProviderLoading.value = true;
        const name = encodeURIComponent(
          props.isAdding ? newRuleProvider.value.name : props.initialValue?.name || ""
        );
        const requestData = props.isAdding ? newRuleProvider.value.data : newRuleProvider.value;
        const method = props.isAdding ? "post" : "patch";
        const result = await props.api[method](
          `/plugin/ClashRuleProvider/rule-providers/${name}`,
          requestData
        );
        if (!result.success) {
          emit("show-error", "保存规则集合失败: " + (result.message || "未知错误"));
          emit("show-snackbar", {
            show: true,
            message: "保存规则集合失败",
            color: "error"
          });
          return;
        }
        emit("show-snackbar", {
          show: true,
          message: props.isAdding ? "规则集合添加成功" : "规则集合更新成功",
          color: "success"
        });
        emit("refresh");
        emit("close");
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", "保存规则集合失败: " + (err.message || "未知错误"));
          emit("show-snackbar", {
            show: true,
            message: "保存规则集合失败",
            color: "error"
          });
        }
      } finally {
        saveRuleProviderLoading.value = false;
      }
    }
    return (_ctx, _cache) => {
      const _component_v_card_title = _resolveComponent$7("v-card-title");
      const _component_v_text_field = _resolveComponent$7("v-text-field");
      const _component_v_select = _resolveComponent$7("v-select");
      const _component_v_chip = _resolveComponent$7("v-chip");
      const _component_v_combobox = _resolveComponent$7("v-combobox");
      const _component_v_card_text = _resolveComponent$7("v-card-text");
      const _component_v_spacer = _resolveComponent$7("v-spacer");
      const _component_v_btn = _resolveComponent$7("v-btn");
      const _component_v_card_actions = _resolveComponent$7("v-card-actions");
      const _component_v_card = _resolveComponent$7("v-card");
      const _component_v_form = _resolveComponent$7("v-form");
      const _component_v_dialog = _resolveComponent$7("v-dialog");
      return _openBlock$7(), _createBlock$7(_component_v_dialog, {
        "max-width": "40rem",
        "model-value": true,
        persistent: ""
      }, {
        default: _withCtx$7(() => [
          _createVNode$7(_component_v_form, {
            ref_key: "ruleProvidersForm",
            ref: ruleProvidersForm,
            onSubmit: _withModifiers$1(saveRuleProvider, ["prevent"])
          }, {
            default: _withCtx$7(() => [
              _createVNode$7(_component_v_card, null, {
                default: _withCtx$7(() => [
                  _createVNode$7(_component_v_card_title, null, {
                    default: _withCtx$7(() => [
                      _createTextVNode$7(_toDisplayString$7(__props.isAdding ? "添加规则集合" : "编辑规则集合"), 1)
                    ]),
                    _: 1
                  }),
                  _createVNode$7(_component_v_card_text, null, {
                    default: _withCtx$7(() => [
                      _createVNode$7(_component_v_text_field, {
                        modelValue: newRuleProvider.value.name,
                        "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => newRuleProvider.value.name = $event),
                        label: "name",
                        required: "",
                        rules: [(v) => !!v || "名称不能为空"],
                        class: "mb-4"
                      }, null, 8, ["modelValue", "rules"]),
                      _createVNode$7(_component_v_select, {
                        modelValue: newRuleProvider.value.data.type,
                        "onUpdate:modelValue": _cache[1] || (_cache[1] = ($event) => newRuleProvider.value.data.type = $event),
                        items: ruleProviderTypes,
                        label: "type",
                        required: "",
                        rules: [(v) => !!v || "类型不能为空"],
                        class: "mb-4"
                      }, null, 8, ["modelValue", "rules"]),
                      newRuleProvider.value.data.type === "http" ? (_openBlock$7(), _createBlock$7(_component_v_text_field, {
                        key: 0,
                        modelValue: newRuleProvider.value.data.url,
                        "onUpdate:modelValue": _cache[2] || (_cache[2] = ($event) => newRuleProvider.value.data.url = $event),
                        label: "url",
                        required: "",
                        rules: [(v) => !!v || "URL 不能为空", (v) => _unref$6(isValidUrl)(v) || "请输入有效的 URL"],
                        class: "mb-4",
                        hint: "当类型为 http 时必须配置"
                      }, null, 8, ["modelValue", "rules"])) : _createCommentVNode$4("", true),
                      newRuleProvider.value.data.type === "file" ? (_openBlock$7(), _createBlock$7(_component_v_text_field, {
                        key: 1,
                        modelValue: newRuleProvider.value.data.path,
                        "onUpdate:modelValue": _cache[3] || (_cache[3] = ($event) => newRuleProvider.value.data.path = $event),
                        label: "path",
                        required: "",
                        rules: [(v) => !!v || "当类型为文件时，路径不能为空"],
                        class: "mb-4",
                        hint: "文件路径，不填写时会使用 url 的 MD5 作为文件名"
                      }, null, 8, ["modelValue", "rules"])) : _createCommentVNode$4("", true),
                      _createVNode$7(_component_v_text_field, {
                        modelValue: newRuleProvider.value.data.interval,
                        "onUpdate:modelValue": _cache[4] || (_cache[4] = ($event) => newRuleProvider.value.data.interval = $event),
                        modelModifiers: { number: true },
                        label: "interval",
                        class: "mb-4",
                        type: "number",
                        min: "0",
                        suffix: "s",
                        hint: "Provider 的更新间隔",
                        clearable: "",
                        rules: [(v) => v === null || v === void 0 || v >= 0 || "更新间隔不能为负数"]
                      }, null, 8, ["modelValue", "rules"]),
                      _createVNode$7(_component_v_select, {
                        modelValue: newRuleProvider.value.data.behavior,
                        "onUpdate:modelValue": _cache[5] || (_cache[5] = ($event) => newRuleProvider.value.data.behavior = $event),
                        items: ruleProviderBehaviorTypes,
                        label: "behavior",
                        class: "mb-4",
                        hint: "对应不同格式的 rule-provider 文件"
                      }, null, 8, ["modelValue"]),
                      _createVNode$7(_component_v_select, {
                        modelValue: newRuleProvider.value.data.format,
                        "onUpdate:modelValue": _cache[6] || (_cache[6] = ($event) => newRuleProvider.value.data.format = $event),
                        items: ruleProviderFormatTypes,
                        label: "format",
                        class: "mb-4",
                        hint: "mrs目前 behavior 仅支持 domain/ipcidr"
                      }, null, 8, ["modelValue"]),
                      _createVNode$7(_component_v_text_field, {
                        modelValue: newRuleProvider.value.data["size-limit"],
                        "onUpdate:modelValue": _cache[7] || (_cache[7] = ($event) => newRuleProvider.value.data["size-limit"] = $event),
                        modelModifiers: { number: true },
                        label: "size-limit",
                        class: "mb-4",
                        type: "number",
                        min: "0",
                        suffix: "byte(s)",
                        hint: "可下载文件的最大大小，0 表示无限制",
                        rules: [(v) => v === null || v === void 0 || v >= 0 || "大小限制不能为负数"]
                      }, null, 8, ["modelValue", "rules"]),
                      newRuleProvider.value.data.type === "inline" ? (_openBlock$7(), _createBlock$7(_component_v_combobox, {
                        key: 2,
                        modelValue: newRuleProvider.value.data.payload,
                        "onUpdate:modelValue": _cache[8] || (_cache[8] = ($event) => newRuleProvider.value.data.payload = $event),
                        multiple: "",
                        chips: "",
                        "closable-chips": "",
                        clearable: "",
                        label: "payload",
                        required: "",
                        rules: [(v) => !!v || "当类型为 inline 时，内容不能为空"],
                        class: "mb-4",
                        hint: "当类型为 inline 时才有效，按回车确认输入",
                        row: ""
                      }, {
                        chip: _withCtx$7(({ props: props2, item }) => [
                          _createVNode$7(_component_v_chip, _mergeProps$6(props2, {
                            closable: "",
                            size: "small"
                          }), {
                            default: _withCtx$7(() => [
                              _createTextVNode$7(_toDisplayString$7(item.value), 1)
                            ]),
                            _: 2
                          }, 1040)
                        ]),
                        _: 1
                      }, 8, ["modelValue", "rules"])) : _createCommentVNode$4("", true)
                    ]),
                    _: 1
                  }),
                  _createVNode$7(_component_v_card_actions, null, {
                    default: _withCtx$7(() => [
                      _createVNode$7(_component_v_spacer),
                      _createVNode$7(_component_v_btn, {
                        color: "secondary",
                        onClick: _cache[9] || (_cache[9] = ($event) => emit("close"))
                      }, {
                        default: _withCtx$7(() => _cache[10] || (_cache[10] = [
                          _createTextVNode$7("取消")
                        ])),
                        _: 1
                      }),
                      _createVNode$7(_component_v_btn, {
                        color: "primary",
                        type: "submit",
                        loading: saveRuleProviderLoading.value
                      }, {
                        default: _withCtx$7(() => _cache[11] || (_cache[11] = [
                          _createTextVNode$7("保存 ")
                        ])),
                        _: 1
                      }, 8, ["loading"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          }, 512)
        ]),
        _: 1
      });
    };
  }
});

const {defineComponent:_defineComponent$6} = await importShared('vue');

const {resolveComponent:_resolveComponent$6,createVNode:_createVNode$6,withCtx:_withCtx$6,createElementVNode:_createElementVNode$5,renderList:_renderList$4,Fragment:_Fragment$4,openBlock:_openBlock$6,createElementBlock:_createElementBlock$4,createBlock:_createBlock$6,unref:_unref$5,toDisplayString:_toDisplayString$6,createTextVNode:_createTextVNode$6,mergeProps:_mergeProps$5,createCommentVNode:_createCommentVNode$3} = await importShared('vue');

const _hoisted_1$4 = { class: "mb-2 position-relative" };
const _hoisted_2$4 = { class: "pa-4" };
const _hoisted_3$4 = { class: "d-none d-sm-flex clash-data-table" };
const _hoisted_4$4 = { class: "d-sm-none" };
const _hoisted_5$2 = {
  class: "pa-4",
  style: { "min-height": "4rem" }
};
const {ref: ref$4,computed: computed$2,toRaw: toRaw$2} = await importShared('vue');
const _sfc_main$6 = /* @__PURE__ */ _defineComponent$6({
  __name: "RuleProvidersTab",
  props: {
    ruleProviders: {},
    api: {}
  },
  emits: ["refresh", "show-snackbar", "show-error", "show-yaml", "edit-visibility"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const searchRuleProviders = ref$4("");
    const pageRulProviders = ref$4(1);
    const itemsPerPageRuleProviders = ref$4(10);
    const ruleProviderDialogVisible = ref$4(false);
    const editingRuleProvider = ref$4(null);
    const editingRuleProviderName = ref$4(null);
    const loading = ref$4(false);
    const filteredExtraRuleProviders = computed$2(() => {
      if (!searchRuleProviders.value) return props.ruleProviders;
      const keyword = searchRuleProviders.value.toLowerCase();
      return props.ruleProviders.filter(
        (item) => Object.values(item).some((val) => String(val).toLowerCase().includes(keyword))
      );
    });
    const paginatedExtraRuleProviders = computed$2(() => {
      const start = (pageRulProviders.value - 1) * itemsPerPageRuleProviders.value;
      const end = start + itemsPerPageRuleProviders.value;
      return filteredExtraRuleProviders.value.slice(start, end);
    });
    const pageCountExtraRuleProviders = computed$2(() => {
      if (itemsPerPageRuleProviders.value === -1) {
        return 1;
      }
      return Math.ceil(props.ruleProviders.length / itemsPerPageRuleProviders.value);
    });
    function openAddRuleProviderDialog() {
      editingRuleProviderName.value = null;
      editingRuleProvider.value = null;
      ruleProviderDialogVisible.value = true;
    }
    function editRuleProvider(name) {
      const ruleProvider = props.ruleProviders.find((r) => r.name === name);
      if (ruleProvider) {
        editingRuleProviderName.value = name;
        editingRuleProvider.value = structuredClone(toRaw$2(ruleProvider));
        ruleProviderDialogVisible.value = true;
      }
    }
    async function deleteRuleProvider(name) {
      loading.value = true;
      try {
        const n = encodeURIComponent(name);
        await props.api.delete(`/plugin/ClashRuleProvider/rule-providers/${n}`);
        emit("refresh", ["rule-providers"]);
      } catch (err) {
        if (err instanceof Error) emit("show-error", err.message || "删除规则集合失败");
      } finally {
        loading.value = false;
      }
    }
    async function handleStatusChange(name, disabled) {
      loading.value = true;
      try {
        const provider = props.ruleProviders.find((p) => p.name === name);
        if (!provider) {
          emit("show-error", "Rule provider not found");
          return;
        }
        const n = encodeURIComponent(name);
        const newMeta = { ...provider.meta, disabled };
        await props.api.patch(`/plugin/ClashRuleProvider/rule-providers/${n}/meta`, newMeta);
        emit("refresh", ["rule-providers"]);
      } catch (err) {
        if (err instanceof Error) {
          emit("show-error", err.message || "更新规则集合状态失败");
        }
      } finally {
        loading.value = false;
      }
    }
    function editVisibility(name) {
      const provider = props.ruleProviders.find((p) => p.name === name);
      if (!provider) {
        emit("show-error", "Rule provider not found");
        return;
      }
      const n = encodeURIComponent(name);
      emit(
        "edit-visibility",
        provider.meta,
        `/plugin/ClashRuleProvider/rule-providers/${n}/meta`,
        "rule-providers"
      );
    }
    function closeRuleProviderDialog() {
      editingRuleProviderName.value = null;
      ruleProviderDialogVisible.value = false;
    }
    return (_ctx, _cache) => {
      const _component_v_progress_circular = _resolveComponent$6("v-progress-circular");
      const _component_v_overlay = _resolveComponent$6("v-overlay");
      const _component_v_text_field = _resolveComponent$6("v-text-field");
      const _component_v_col = _resolveComponent$6("v-col");
      const _component_v_btn = _resolveComponent$6("v-btn");
      const _component_v_btn_group = _resolveComponent$6("v-btn-group");
      const _component_v_row = _resolveComponent$6("v-row");
      const _component_v_pagination = _resolveComponent$6("v-pagination");
      const _component_v_list_item_title = _resolveComponent$6("v-list-item-title");
      const _component_v_list_item = _resolveComponent$6("v-list-item");
      const _component_v_list = _resolveComponent$6("v-list");
      const _component_v_menu = _resolveComponent$6("v-menu");
      const _component_v_divider = _resolveComponent$6("v-divider");
      return _openBlock$6(), _createElementBlock$4("div", _hoisted_1$4, [
        _createVNode$6(_component_v_overlay, {
          modelValue: loading.value,
          "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => loading.value = $event),
          contained: "",
          class: "align-center justify-center"
        }, {
          default: _withCtx$6(() => [
            _createVNode$6(_component_v_progress_circular, {
              indeterminate: "",
              color: "primary"
            })
          ]),
          _: 1
        }, 8, ["modelValue"]),
        _createElementVNode$5("div", _hoisted_2$4, [
          _createVNode$6(_component_v_row, {
            align: "center",
            "no-gutters": ""
          }, {
            default: _withCtx$6(() => [
              _createVNode$6(_component_v_col, {
                cols: "10",
                sm: "6",
                class: "d-flex justify-start"
              }, {
                default: _withCtx$6(() => [
                  _createVNode$6(_component_v_text_field, {
                    modelValue: searchRuleProviders.value,
                    "onUpdate:modelValue": _cache[1] || (_cache[1] = ($event) => searchRuleProviders.value = $event),
                    label: "搜索规则集合",
                    clearable: "",
                    density: "compact",
                    variant: "solo-filled",
                    "hide-details": "",
                    class: "search-field",
                    "prepend-inner-icon": "mdi-magnify",
                    flat: "",
                    rounded: "pill",
                    "single-line": "",
                    disabled: loading.value
                  }, null, 8, ["modelValue", "disabled"])
                ]),
                _: 1
              }),
              _createVNode$6(_component_v_col, {
                cols: "2",
                sm: "6",
                class: "d-flex justify-end"
              }, {
                default: _withCtx$6(() => [
                  _createVNode$6(_component_v_btn_group, {
                    variant: "outlined",
                    rounded: ""
                  }, {
                    default: _withCtx$6(() => [
                      _createVNode$6(_component_v_btn, {
                        icon: "mdi-plus",
                        disabled: loading.value,
                        onClick: openAddRuleProviderDialog
                      }, null, 8, ["disabled"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _createElementVNode$5("div", _hoisted_3$4, [
          _createVNode$6(_sfc_main$9, {
            "items-per-page": itemsPerPageRuleProviders.value,
            page: pageRulProviders.value,
            "rule-providers": filteredExtraRuleProviders.value,
            onEditRuleProvider: editRuleProvider,
            onDeleteRuleProvider: deleteRuleProvider,
            onShowYaml: _cache[2] || (_cache[2] = (o) => emit("show-yaml", o)),
            onChangeStatus: handleStatusChange,
            onEditVisibility: editVisibility
          }, null, 8, ["items-per-page", "page", "rule-providers"])
        ]),
        _createElementVNode$5("div", _hoisted_4$4, [
          _createVNode$6(_component_v_row, null, {
            default: _withCtx$6(() => [
              (_openBlock$6(true), _createElementBlock$4(_Fragment$4, null, _renderList$4(paginatedExtraRuleProviders.value, (item) => {
                return _openBlock$6(), _createBlock$6(_component_v_col, {
                  key: item.name,
                  cols: "12"
                }, {
                  default: _withCtx$6(() => [
                    _createVNode$6(RuleProviderCard, {
                      "rule-provider-data": item,
                      onEditRuleProvider: editRuleProvider,
                      onDeleteRuleProvider: deleteRuleProvider,
                      onShowYaml: _cache[3] || (_cache[3] = (o) => emit("show-yaml", o)),
                      onChangeStatus: handleStatusChange,
                      onEditVisibility: editVisibility
                    }, null, 8, ["rule-provider-data"])
                  ]),
                  _: 2
                }, 1024);
              }), 128))
            ]),
            _: 1
          })
        ]),
        _createElementVNode$5("div", _hoisted_5$2, [
          _createVNode$6(_component_v_row, {
            align: "center",
            "no-gutters": ""
          }, {
            default: _withCtx$6(() => [
              _createVNode$6(_component_v_col, {
                cols: "2",
                md: "1"
              }),
              _createVNode$6(_component_v_col, {
                cols: "8",
                md: "10",
                class: "d-flex justify-center"
              }, {
                default: _withCtx$6(() => [
                  _createVNode$6(_component_v_pagination, {
                    modelValue: pageRulProviders.value,
                    "onUpdate:modelValue": _cache[4] || (_cache[4] = ($event) => pageRulProviders.value = $event),
                    length: pageCountExtraRuleProviders.value,
                    "total-visible": "5",
                    rounded: "circle",
                    class: "d-none d-sm-flex my-0",
                    disabled: loading.value
                  }, null, 8, ["modelValue", "length", "disabled"]),
                  _createVNode$6(_component_v_pagination, {
                    modelValue: pageRulProviders.value,
                    "onUpdate:modelValue": _cache[5] || (_cache[5] = ($event) => pageRulProviders.value = $event),
                    length: pageCountExtraRuleProviders.value,
                    "total-visible": "0",
                    rounded: "circle",
                    class: "d-sm-none my-0",
                    disabled: loading.value
                  }, null, 8, ["modelValue", "length", "disabled"])
                ]),
                _: 1
              }),
              _createVNode$6(_component_v_col, {
                cols: "2",
                md: "1",
                class: "d-flex justify-end"
              }, {
                default: _withCtx$6(() => [
                  _createVNode$6(_component_v_menu, null, {
                    activator: _withCtx$6(({ props: props2 }) => [
                      _createVNode$6(_component_v_btn, _mergeProps$5(props2, {
                        icon: "",
                        rounded: "circle",
                        variant: "tonal",
                        disabled: loading.value
                      }), {
                        default: _withCtx$6(() => [
                          _createTextVNode$6(_toDisplayString$6(_unref$5(pageTitle)(itemsPerPageRuleProviders.value)), 1)
                        ]),
                        _: 2
                      }, 1040, ["disabled"])
                    ]),
                    default: _withCtx$6(() => [
                      _createVNode$6(_component_v_list, null, {
                        default: _withCtx$6(() => [
                          (_openBlock$6(true), _createElementBlock$4(_Fragment$4, null, _renderList$4(_unref$5(itemsPerPageOptions), (item, index) => {
                            return _openBlock$6(), _createBlock$6(_component_v_list_item, {
                              key: index,
                              value: item.value,
                              onClick: ($event) => itemsPerPageRuleProviders.value = item.value
                            }, {
                              default: _withCtx$6(() => [
                                _createVNode$6(_component_v_list_item_title, null, {
                                  default: _withCtx$6(() => [
                                    _createTextVNode$6(_toDisplayString$6(item.title), 1)
                                  ]),
                                  _: 2
                                }, 1024)
                              ]),
                              _: 2
                            }, 1032, ["value", "onClick"]);
                          }), 128))
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _createVNode$6(_component_v_divider),
        ruleProviderDialogVisible.value ? (_openBlock$6(), _createBlock$6(_sfc_main$7, {
          key: 0,
          modelValue: ruleProviderDialogVisible.value,
          "onUpdate:modelValue": _cache[6] || (_cache[6] = ($event) => ruleProviderDialogVisible.value = $event),
          "initial-value": editingRuleProvider.value,
          "is-adding": editingRuleProviderName.value === null,
          api: _ctx.api,
          onClose: closeRuleProviderDialog,
          onRefresh: _cache[7] || (_cache[7] = ($event) => emit("refresh", ["rule-providers"])),
          onShowSnackbar: _cache[8] || (_cache[8] = (val) => emit("show-snackbar", val)),
          onShowError: _cache[9] || (_cache[9] = (msg) => emit("show-error", msg))
        }, null, 8, ["modelValue", "initial-value", "is-adding", "api"])) : _createCommentVNode$3("", true)
      ]);
    };
  }
});

const {defineComponent:_defineComponent$5} = await importShared('vue');

const {unref:_unref$4,toDisplayString:_toDisplayString$5,createTextVNode:_createTextVNode$5,resolveComponent:_resolveComponent$5,withCtx:_withCtx$5,createVNode:_createVNode$5,renderList:_renderList$3,Fragment:_Fragment$3,openBlock:_openBlock$5,createElementBlock:_createElementBlock$3,createBlock:_createBlock$5,mergeProps:_mergeProps$4} = await importShared('vue');

const {ref: ref$3} = await importShared('vue');
const _sfc_main$5 = /* @__PURE__ */ _defineComponent$5({
  __name: "HostsTable",
  props: {
    hosts: {
      type: Array,
      required: true
    },
    search: {
      type: String,
      default: ""
    },
    page: {
      type: Number,
      required: true
    },
    itemsPerPage: {
      type: Number,
      required: true
    }
  },
  emits: ["edit", "delete"],
  setup(__props) {
    const headersHosts = ref$3([
      { title: "域名", key: "domain", sortable: true },
      { title: "IP", key: "value", sortable: false },
      { title: "Cloudflare CDN", key: "using_cloudflare", sortable: false },
      { title: "", key: "actions", sortable: false, width: "1rem" }
    ]);
    return (_ctx, _cache) => {
      const _component_v_chip = _resolveComponent$5("v-chip");
      const _component_v_icon = _resolveComponent$5("v-icon");
      const _component_v_btn = _resolveComponent$5("v-btn");
      const _component_v_list_item_title = _resolveComponent$5("v-list-item-title");
      const _component_v_list_item = _resolveComponent$5("v-list-item");
      const _component_v_list = _resolveComponent$5("v-list");
      const _component_v_menu = _resolveComponent$5("v-menu");
      const _component_v_data_table = _resolveComponent$5("v-data-table");
      return _openBlock$5(), _createBlock$5(_component_v_data_table, {
        headers: headersHosts.value,
        items: __props.hosts,
        search: __props.search,
        page: __props.page,
        "items-per-page": __props.itemsPerPage,
        "items-per-page-options": _unref$4(itemsPerPageOptions),
        class: "px-4",
        density: "compact",
        "hide-default-footer": "",
        "fixed-header": "",
        "item-key": "domain"
      }, {
        "item.domain": _withCtx$5(({ item }) => [
          _createVNode$5(_component_v_chip, {
            size: "small",
            pill: "",
            color: "secondary"
          }, {
            default: _withCtx$5(() => [
              _createTextVNode$5(_toDisplayString$5(item.domain), 1)
            ]),
            _: 2
          }, 1024)
        ]),
        "item.value": _withCtx$5(({ item }) => [
          (_openBlock$5(true), _createElementBlock$3(_Fragment$3, null, _renderList$3(item.value, (ip) => {
            return _openBlock$5(), _createBlock$5(_component_v_chip, {
              key: ip,
              size: "small",
              class: "ma-1",
              variant: "tonal"
            }, {
              default: _withCtx$5(() => [
                _createTextVNode$5(_toDisplayString$5(ip), 1)
              ]),
              _: 2
            }, 1024);
          }), 128))
        ]),
        "item.using_cloudflare": _withCtx$5(({ item }) => [
          _createVNode$5(_component_v_chip, {
            color: _unref$4(getBoolColor)(item.using_cloudflare),
            size: "small",
            variant: "tonal"
          }, {
            default: _withCtx$5(() => [
              _createTextVNode$5(_toDisplayString$5(item.using_cloudflare ? "是" : "否"), 1)
            ]),
            _: 2
          }, 1032, ["color"])
        ]),
        "item.actions": _withCtx$5(({ item }) => [
          _createVNode$5(_component_v_menu, { "min-width": "120" }, {
            activator: _withCtx$5(({ props }) => [
              _createVNode$5(_component_v_btn, _mergeProps$4({
                color: "secondary",
                icon: "",
                size: "small",
                variant: "text"
              }, props), {
                default: _withCtx$5(() => [
                  _createVNode$5(_component_v_icon, null, {
                    default: _withCtx$5(() => _cache[0] || (_cache[0] = [
                      _createTextVNode$5("mdi-dots-vertical")
                    ])),
                    _: 1
                  })
                ]),
                _: 2
              }, 1040)
            ]),
            default: _withCtx$5(() => [
              _createVNode$5(_component_v_list, { density: "compact" }, {
                default: _withCtx$5(() => [
                  _createVNode$5(_component_v_list_item, {
                    onClick: ($event) => _ctx.$emit("edit", item.domain)
                  }, {
                    prepend: _withCtx$5(() => [
                      _createVNode$5(_component_v_icon, {
                        size: "small",
                        color: "primary"
                      }, {
                        default: _withCtx$5(() => _cache[1] || (_cache[1] = [
                          _createTextVNode$5("mdi-file-edit-outline")
                        ])),
                        _: 1
                      })
                    ]),
                    default: _withCtx$5(() => [
                      _createVNode$5(_component_v_list_item_title, null, {
                        default: _withCtx$5(() => _cache[2] || (_cache[2] = [
                          _createTextVNode$5("编辑")
                        ])),
                        _: 1
                      })
                    ]),
                    _: 2
                  }, 1032, ["onClick"]),
                  _createVNode$5(_component_v_list_item, {
                    onClick: ($event) => _ctx.$emit("delete", item.domain)
                  }, {
                    prepend: _withCtx$5(() => [
                      _createVNode$5(_component_v_icon, {
                        size: "small",
                        color: "error"
                      }, {
                        default: _withCtx$5(() => _cache[3] || (_cache[3] = [
                          _createTextVNode$5("mdi-trash-can-outline")
                        ])),
                        _: 1
                      })
                    ]),
                    default: _withCtx$5(() => [
                      _createVNode$5(_component_v_list_item_title, null, {
                        default: _withCtx$5(() => _cache[4] || (_cache[4] = [
                          _createTextVNode$5("删除")
                        ])),
                        _: 1
                      })
                    ]),
                    _: 2
                  }, 1032, ["onClick"])
                ]),
                _: 2
              }, 1024)
            ]),
            _: 2
          }, 1024)
        ]),
        _: 1
      }, 8, ["headers", "items", "search", "page", "items-per-page", "items-per-page-options"]);
    };
  }
});

const {defineComponent:_defineComponent$4} = await importShared('vue');

const {toDisplayString:_toDisplayString$4,createTextVNode:_createTextVNode$4,resolveComponent:_resolveComponent$4,withCtx:_withCtx$4,createVNode:_createVNode$4,unref:_unref$3,mergeProps:_mergeProps$3,openBlock:_openBlock$4,createBlock:_createBlock$4,createCommentVNode:_createCommentVNode$2,createElementVNode:_createElementVNode$4,withModifiers:_withModifiers} = await importShared('vue');

const {ref: ref$2,toRaw: toRaw$1} = await importShared('vue');
const _sfc_main$4 = /* @__PURE__ */ _defineComponent$4({
  __name: "HostDialog",
  props: {
    initialValue: {
      type: Object,
      default: () => ({ ...defaultHost })
    },
    isAdding: {
      type: Boolean,
      default: true
    },
    bestCloudflareIPs: {
      type: Array,
      default: () => []
    },
    api: {
      type: Object,
      required: true
    }
  },
  emits: ["close", "refresh", "show-snackbar", "show-error"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const hostForm = ref$2(null);
    const saveHostLoading = ref$2(false);
    const newHost = ref$2(
      props.isAdding ? { ...defaultHost } : structuredClone(toRaw$1(props.initialValue))
    );
    async function saveHost() {
      const { valid } = await hostForm.value.validate();
      if (!valid) return;
      try {
        saveHostLoading.value = true;
        newHost.value.domain = newHost.value.domain.trim();
        const targetDomain = props.isAdding ? newHost.value.domain : props.initialValue.domain;
        const result = await props.api.post("/plugin/ClashRuleProvider/hosts", {
          domain: targetDomain,
          host: newHost.value
        });
        if (!result.success) {
          emit("show-error", "保存 Host 失败: " + (result.message || "未知错误"));
          emit("show-snackbar", {
            show: true,
            message: "保存 Host 失败",
            color: "error"
          });
          return;
        }
        emit("close");
        emit("refresh");
        emit("show-snackbar", {
          show: true,
          message: props.isAdding ? "Host 添加成功" : "Host 更新成功",
          color: "success"
        });
      } catch (err) {
        emit("show-error", "保存 Host 失败: " + (err.message || "未知错误"));
        emit("show-snackbar", {
          show: true,
          message: "保存 Host 失败",
          color: "error"
        });
      } finally {
        saveHostLoading.value = false;
      }
    }
    return (_ctx, _cache) => {
      const _component_v_card_title = _resolveComponent$4("v-card-title");
      const _component_v_text_field = _resolveComponent$4("v-text-field");
      const _component_v_chip = _resolveComponent$4("v-chip");
      const _component_v_combobox = _resolveComponent$4("v-combobox");
      const _component_v_switch = _resolveComponent$4("v-switch");
      const _component_v_col = _resolveComponent$4("v-col");
      const _component_v_row = _resolveComponent$4("v-row");
      const _component_v_card_text = _resolveComponent$4("v-card-text");
      const _component_v_alert = _resolveComponent$4("v-alert");
      const _component_v_spacer = _resolveComponent$4("v-spacer");
      const _component_v_btn = _resolveComponent$4("v-btn");
      const _component_v_card_actions = _resolveComponent$4("v-card-actions");
      const _component_v_card = _resolveComponent$4("v-card");
      const _component_v_form = _resolveComponent$4("v-form");
      const _component_v_dialog = _resolveComponent$4("v-dialog");
      return _openBlock$4(), _createBlock$4(_component_v_dialog, { "max-width": "40rem" }, {
        default: _withCtx$4(() => [
          _createVNode$4(_component_v_form, {
            ref_key: "hostForm",
            ref: hostForm,
            onSubmit: _withModifiers(saveHost, ["prevent"])
          }, {
            default: _withCtx$4(() => [
              _createVNode$4(_component_v_card, null, {
                default: _withCtx$4(() => [
                  _createVNode$4(_component_v_card_title, null, {
                    default: _withCtx$4(() => [
                      _createTextVNode$4(_toDisplayString$4(__props.isAdding ? "添加 Host" : "编辑 Host"), 1)
                    ]),
                    _: 1
                  }),
                  _createVNode$4(_component_v_card_text, null, {
                    default: _withCtx$4(() => [
                      _createVNode$4(_component_v_text_field, {
                        modelValue: newHost.value.domain,
                        "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => newHost.value.domain = $event),
                        label: "域名",
                        required: "",
                        rules: [(v) => !!v || "域名不能为空"],
                        class: "mb-4"
                      }, null, 8, ["modelValue", "rules"]),
                      !newHost.value.using_cloudflare ? (_openBlock$4(), _createBlock$4(_component_v_combobox, {
                        key: 0,
                        modelValue: newHost.value.value,
                        "onUpdate:modelValue": _cache[1] || (_cache[1] = ($event) => newHost.value.value = $event),
                        multiple: "",
                        chips: "",
                        "closable-chips": "",
                        clearable: "",
                        label: "IP",
                        required: "",
                        rules: [_unref$3(validateIPs)],
                        class: "mb-4",
                        hint: "一个或多个 IP 地址"
                      }, {
                        chip: _withCtx$4(({ props: props2, item }) => [
                          _createVNode$4(_component_v_chip, _mergeProps$3(props2, {
                            closable: "",
                            size: "small"
                          }), {
                            default: _withCtx$4(() => [
                              _createTextVNode$4(_toDisplayString$4(item.value), 1)
                            ]),
                            _: 2
                          }, 1040)
                        ]),
                        _: 1
                      }, 8, ["modelValue", "rules"])) : _createCommentVNode$2("", true),
                      _createVNode$4(_component_v_row, null, {
                        default: _withCtx$4(() => [
                          _createVNode$4(_component_v_col, {
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx$4(() => [
                              _createVNode$4(_component_v_switch, {
                                modelValue: newHost.value.using_cloudflare,
                                "onUpdate:modelValue": _cache[2] || (_cache[2] = ($event) => newHost.value.using_cloudflare = $event),
                                label: "使用 Cloudflare CDN",
                                inset: "",
                                hint: "设置为 CF 优选 IPs",
                                "persistent-hint": ""
                              }, null, 8, ["modelValue"])
                            ]),
                            _: 1
                          })
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }),
                  __props.bestCloudflareIPs.length === 0 && newHost.value.using_cloudflare ? (_openBlock$4(), _createBlock$4(_component_v_alert, {
                    key: 0,
                    type: "warning",
                    text: "请在「高级选项」配置 Cloudflare CDN 优选 IPs",
                    variant: "outlined",
                    class: "mb-2"
                  })) : _createCommentVNode$2("", true),
                  _createVNode$4(_component_v_alert, {
                    type: "info",
                    variant: "tonal"
                  }, {
                    default: _withCtx$4(() => _cache[4] || (_cache[4] = [
                      _createTextVNode$4(" 支持"),
                      _createElementVNode$4("a", {
                        href: "https://wiki.metacubex.one/handbook/syntax/#_8",
                        target: "_blank"
                      }, "域名通配符", -1)
                    ])),
                    _: 1
                  }),
                  _createVNode$4(_component_v_card_actions, null, {
                    default: _withCtx$4(() => [
                      _createVNode$4(_component_v_spacer),
                      _createVNode$4(_component_v_btn, {
                        color: "secondary",
                        onClick: _cache[3] || (_cache[3] = ($event) => emit("close"))
                      }, {
                        default: _withCtx$4(() => _cache[5] || (_cache[5] = [
                          _createTextVNode$4("取消")
                        ])),
                        _: 1
                      }),
                      _createVNode$4(_component_v_btn, {
                        color: "primary",
                        type: "submit",
                        loading: saveHostLoading.value
                      }, {
                        default: _withCtx$4(() => _cache[6] || (_cache[6] = [
                          _createTextVNode$4("保存 ")
                        ])),
                        _: 1
                      }, 8, ["loading"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          }, 512)
        ]),
        _: 1
      });
    };
  }
});

const {defineComponent:_defineComponent$3} = await importShared('vue');

const {toDisplayString:_toDisplayString$3,createElementVNode:_createElementVNode$3,createTextVNode:_createTextVNode$3,resolveComponent:_resolveComponent$3,withCtx:_withCtx$3,createVNode:_createVNode$3,unref:_unref$2,renderList:_renderList$2,Fragment:_Fragment$2,openBlock:_openBlock$3,createElementBlock:_createElementBlock$2,createBlock:_createBlock$3,mergeProps:_mergeProps$2} = await importShared('vue');

const _hoisted_1$3 = { class: "d-flex justify-space-between align-center px-4 pt-3" };
const _hoisted_2$3 = { class: "d-flex align-center text-truncate" };
const _hoisted_3$3 = ["title"];
const _hoisted_4$3 = { class: "d-flex flex-wrap gap-1" };
const _sfc_main$3 = /* @__PURE__ */ _defineComponent$3({
  __name: "HostCard",
  props: {
    hostData: {
      type: Object,
      required: true
    },
    bestCloudflareIPs: {
      type: Array,
      required: true
    }
  },
  emits: ["editHost", "deleteHost"],
  setup(__props, { emit: __emit }) {
    const emit = __emit;
    return (_ctx, _cache) => {
      const _component_v_col = _resolveComponent$3("v-col");
      const _component_v_chip = _resolveComponent$3("v-chip");
      const _component_v_row = _resolveComponent$3("v-row");
      const _component_v_card_text = _resolveComponent$3("v-card-text");
      const _component_v_divider = _resolveComponent$3("v-divider");
      const _component_v_icon = _resolveComponent$3("v-icon");
      const _component_v_spacer = _resolveComponent$3("v-spacer");
      const _component_v_btn = _resolveComponent$3("v-btn");
      const _component_v_list_item_title = _resolveComponent$3("v-list-item-title");
      const _component_v_list_item = _resolveComponent$3("v-list-item");
      const _component_v_list = _resolveComponent$3("v-list");
      const _component_v_menu = _resolveComponent$3("v-menu");
      const _component_v_card_actions = _resolveComponent$3("v-card-actions");
      const _component_v_card = _resolveComponent$3("v-card");
      return _openBlock$3(), _createBlock$3(_component_v_card, {
        rounded: "lg",
        elevation: "2",
        class: "host-card h-100 transition-swing",
        variant: "tonal"
      }, {
        default: _withCtx$3(() => [
          _createElementVNode$3("div", _hoisted_1$3, [
            _createElementVNode$3("div", _hoisted_2$3, [
              _createElementVNode$3("span", {
                class: "font-weight-bold text-truncate",
                title: __props.hostData.domain
              }, _toDisplayString$3(__props.hostData.domain), 9, _hoisted_3$3)
            ])
          ]),
          _createVNode$3(_component_v_card_text, { class: "pt-2 pb-4" }, {
            default: _withCtx$3(() => [
              _createVNode$3(_component_v_row, {
                "no-gutters": "",
                class: "mb-2 align-center"
              }, {
                default: _withCtx$3(() => [
                  _createVNode$3(_component_v_col, {
                    cols: "3",
                    class: "text-caption text-medium-emphasis"
                  }, {
                    default: _withCtx$3(() => _cache[2] || (_cache[2] = [
                      _createTextVNode$3("类型")
                    ])),
                    _: 1
                  }),
                  _createVNode$3(_component_v_col, { cols: "9" }, {
                    default: _withCtx$3(() => [
                      _createVNode$3(_component_v_chip, {
                        color: _unref$2(getBoolColor)(__props.hostData.using_cloudflare),
                        size: "x-small",
                        label: "",
                        variant: "tonal",
                        class: "font-weight-medium"
                      }, {
                        default: _withCtx$3(() => [
                          _createTextVNode$3(_toDisplayString$3(__props.hostData.using_cloudflare ? "Cloudflare" : "hosts"), 1)
                        ]),
                        _: 1
                      }, 8, ["color"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              }),
              _createVNode$3(_component_v_row, {
                "no-gutters": "",
                class: "align-center"
              }, {
                default: _withCtx$3(() => [
                  _createVNode$3(_component_v_col, {
                    cols: "3",
                    class: "text-caption text-medium-emphasis"
                  }, {
                    default: _withCtx$3(() => _cache[3] || (_cache[3] = [
                      _createTextVNode$3("IP")
                    ])),
                    _: 1
                  }),
                  _createVNode$3(_component_v_col, { cols: "9" }, {
                    default: _withCtx$3(() => [
                      _createElementVNode$3("div", _hoisted_4$3, [
                        (_openBlock$3(true), _createElementBlock$2(_Fragment$2, null, _renderList$2(__props.hostData.using_cloudflare ? __props.bestCloudflareIPs : __props.hostData.value, (ip) => {
                          return _openBlock$3(), _createBlock$3(_component_v_chip, {
                            key: ip,
                            size: "x-small",
                            class: "mr-1 mb-1",
                            variant: "outlined"
                          }, {
                            default: _withCtx$3(() => [
                              _createTextVNode$3(_toDisplayString$3(ip), 1)
                            ]),
                            _: 2
                          }, 1024);
                        }), 128))
                      ])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode$3(_component_v_divider),
          _createVNode$3(_component_v_card_actions, null, {
            default: _withCtx$3(() => [
              _createVNode$3(_component_v_icon, {
                color: __props.hostData.meta.disabled ? "grey" : "success"
              }, {
                default: _withCtx$3(() => [
                  _createTextVNode$3(_toDisplayString$3(__props.hostData.meta.disabled ? "mdi-close-circle-outline" : "mdi-check-circle-outline"), 1)
                ]),
                _: 1
              }, 8, ["color"]),
              _createVNode$3(_component_v_spacer),
              _createVNode$3(_component_v_menu, { "min-width": "140" }, {
                activator: _withCtx$3(({ props }) => [
                  _createVNode$3(_component_v_btn, _mergeProps$2({
                    color: "secondary",
                    icon: "",
                    size: "small",
                    variant: "text"
                  }, props), {
                    default: _withCtx$3(() => [
                      _createVNode$3(_component_v_icon, null, {
                        default: _withCtx$3(() => _cache[4] || (_cache[4] = [
                          _createTextVNode$3("mdi-dots-vertical")
                        ])),
                        _: 1
                      })
                    ]),
                    _: 2
                  }, 1040)
                ]),
                default: _withCtx$3(() => [
                  _createVNode$3(_component_v_list, { density: "compact" }, {
                    default: _withCtx$3(() => [
                      _createVNode$3(_component_v_list_item, {
                        onClick: _cache[0] || (_cache[0] = ($event) => emit("editHost", __props.hostData.domain))
                      }, {
                        prepend: _withCtx$3(() => [
                          _createVNode$3(_component_v_icon, {
                            size: "small",
                            color: "primary"
                          }, {
                            default: _withCtx$3(() => _cache[5] || (_cache[5] = [
                              _createTextVNode$3("mdi-file-edit-outline")
                            ])),
                            _: 1
                          })
                        ]),
                        default: _withCtx$3(() => [
                          _createVNode$3(_component_v_list_item_title, null, {
                            default: _withCtx$3(() => _cache[6] || (_cache[6] = [
                              _createTextVNode$3("编辑")
                            ])),
                            _: 1
                          })
                        ]),
                        _: 1
                      }),
                      _createVNode$3(_component_v_list_item, {
                        onClick: _cache[1] || (_cache[1] = ($event) => emit("deleteHost", __props.hostData.domain))
                      }, {
                        prepend: _withCtx$3(() => [
                          _createVNode$3(_component_v_icon, {
                            size: "small",
                            color: "error"
                          }, {
                            default: _withCtx$3(() => _cache[7] || (_cache[7] = [
                              _createTextVNode$3("mdi-trash-can-outline")
                            ])),
                            _: 1
                          })
                        ]),
                        default: _withCtx$3(() => [
                          _createVNode$3(_component_v_list_item_title, null, {
                            default: _withCtx$3(() => _cache[8] || (_cache[8] = [
                              _createTextVNode$3("删除")
                            ])),
                            _: 1
                          })
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _: 1
      });
    };
  }
});

const HostCard = /* @__PURE__ */ _export_sfc(_sfc_main$3, [["__scopeId", "data-v-a5d6e0e6"]]);

const {defineComponent:_defineComponent$2} = await importShared('vue');

const {resolveComponent:_resolveComponent$2,createVNode:_createVNode$2,withCtx:_withCtx$2,createElementVNode:_createElementVNode$2,renderList:_renderList$1,Fragment:_Fragment$1,openBlock:_openBlock$2,createElementBlock:_createElementBlock$1,createBlock:_createBlock$2,unref:_unref$1,toDisplayString:_toDisplayString$2,createTextVNode:_createTextVNode$2,mergeProps:_mergeProps$1,createCommentVNode:_createCommentVNode$1} = await importShared('vue');

const _hoisted_1$2 = { class: "mb-2 position-relative" };
const _hoisted_2$2 = { class: "pa-4" };
const _hoisted_3$2 = { class: "d-none d-sm-flex clash-data-table" };
const _hoisted_4$2 = { class: "d-sm-none" };
const _hoisted_5$1 = {
  class: "pa-4",
  style: { "min-height": "4rem" }
};
const {ref: ref$1,computed: computed$1,toRaw} = await importShared('vue');
const _sfc_main$2 = /* @__PURE__ */ _defineComponent$2({
  __name: "HostsTab",
  props: {
    hosts: {},
    bestCloudflareIPs: {},
    api: {}
  },
  emits: ["refresh", "show-snackbar", "show-error"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const searchHosts = ref$1("");
    const pageHosts = ref$1(1);
    const itemsPerPageHosts = ref$1(10);
    const hostDialogVisible = ref$1(false);
    const currentHost = ref$1({ ...defaultHost });
    const isAdding = ref$1(true);
    const loading = ref$1(false);
    const filteredHosts = computed$1(() => {
      if (!searchHosts.value) return props.hosts;
      const keyword = searchHosts.value.toLowerCase();
      return props.hosts.filter(
        (item) => Object.values(item).some((val) => String(val).toLowerCase().includes(keyword))
      );
    });
    const paginatedHosts = computed$1(() => {
      const start = (pageHosts.value - 1) * itemsPerPageHosts.value;
      const end = start + itemsPerPageHosts.value;
      return filteredHosts.value.slice(start, end);
    });
    const pageCountHosts = computed$1(() => {
      if (itemsPerPageHosts.value === -1) {
        return 1;
      }
      return Math.ceil(props.hosts.length / itemsPerPageHosts.value);
    });
    function openAddHostDialog() {
      currentHost.value = { ...defaultHost };
      isAdding.value = true;
      hostDialogVisible.value = true;
    }
    function editHost(domain) {
      const hostItem = props.hosts.find((r) => r.domain === domain);
      if (hostItem) {
        currentHost.value = structuredClone(toRaw(hostItem));
        isAdding.value = false;
        hostDialogVisible.value = true;
      }
    }
    async function deleteHost(name) {
      loading.value = true;
      try {
        await props.api.delete(`/plugin/ClashRuleProvider/hosts/${encodeURIComponent(name)}`);
        emit("refresh");
      } catch (err) {
        emit("show-error", err.message || "删除 host 失败");
      } finally {
        loading.value = false;
      }
    }
    return (_ctx, _cache) => {
      const _component_v_progress_circular = _resolveComponent$2("v-progress-circular");
      const _component_v_overlay = _resolveComponent$2("v-overlay");
      const _component_v_text_field = _resolveComponent$2("v-text-field");
      const _component_v_col = _resolveComponent$2("v-col");
      const _component_v_btn = _resolveComponent$2("v-btn");
      const _component_v_btn_group = _resolveComponent$2("v-btn-group");
      const _component_v_row = _resolveComponent$2("v-row");
      const _component_v_pagination = _resolveComponent$2("v-pagination");
      const _component_v_list_item_title = _resolveComponent$2("v-list-item-title");
      const _component_v_list_item = _resolveComponent$2("v-list-item");
      const _component_v_list = _resolveComponent$2("v-list");
      const _component_v_menu = _resolveComponent$2("v-menu");
      const _component_v_divider = _resolveComponent$2("v-divider");
      return _openBlock$2(), _createElementBlock$1(_Fragment$1, null, [
        _createElementVNode$2("div", _hoisted_1$2, [
          _createVNode$2(_component_v_overlay, {
            modelValue: loading.value,
            "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => loading.value = $event),
            contained: "",
            class: "align-center justify-center"
          }, {
            default: _withCtx$2(() => [
              _createVNode$2(_component_v_progress_circular, {
                indeterminate: "",
                color: "primary"
              })
            ]),
            _: 1
          }, 8, ["modelValue"]),
          _createElementVNode$2("div", _hoisted_2$2, [
            _createVNode$2(_component_v_row, {
              align: "center",
              "no-gutters": ""
            }, {
              default: _withCtx$2(() => [
                _createVNode$2(_component_v_col, {
                  cols: "10",
                  sm: "6",
                  class: "d-flex justify-start"
                }, {
                  default: _withCtx$2(() => [
                    _createVNode$2(_component_v_text_field, {
                      modelValue: searchHosts.value,
                      "onUpdate:modelValue": _cache[1] || (_cache[1] = ($event) => searchHosts.value = $event),
                      label: "搜索Hosts",
                      clearable: "",
                      density: "compact",
                      variant: "solo-filled",
                      "hide-details": "",
                      class: "search-field",
                      "prepend-inner-icon": "mdi-magnify",
                      flat: "",
                      rounded: "pill",
                      "single-line": "",
                      disabled: loading.value
                    }, null, 8, ["modelValue", "disabled"])
                  ]),
                  _: 1
                }),
                _createVNode$2(_component_v_col, {
                  cols: "2",
                  sm: "6",
                  class: "d-flex justify-end"
                }, {
                  default: _withCtx$2(() => [
                    _createVNode$2(_component_v_btn_group, {
                      variant: "outlined",
                      rounded: ""
                    }, {
                      default: _withCtx$2(() => [
                        _createVNode$2(_component_v_btn, {
                          icon: "mdi-plus",
                          disabled: loading.value,
                          onClick: openAddHostDialog
                        }, null, 8, ["disabled"])
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _createElementVNode$2("div", _hoisted_3$2, [
            _createVNode$2(_sfc_main$5, {
              hosts: _ctx.hosts,
              search: searchHosts.value,
              page: pageHosts.value,
              "items-per-page": itemsPerPageHosts.value,
              onEdit: editHost,
              onDelete: deleteHost
            }, null, 8, ["hosts", "search", "page", "items-per-page"])
          ]),
          _createElementVNode$2("div", _hoisted_4$2, [
            _createVNode$2(_component_v_row, null, {
              default: _withCtx$2(() => [
                (_openBlock$2(true), _createElementBlock$1(_Fragment$1, null, _renderList$1(paginatedHosts.value, (item) => {
                  return _openBlock$2(), _createBlock$2(_component_v_col, {
                    key: item.domain,
                    cols: "12"
                  }, {
                    default: _withCtx$2(() => [
                      _createVNode$2(HostCard, {
                        "host-data": item,
                        "best-cloudflare-i-ps": _ctx.bestCloudflareIPs,
                        onEditHost: editHost,
                        onDeleteHost: deleteHost
                      }, null, 8, ["host-data", "best-cloudflare-i-ps"])
                    ]),
                    _: 2
                  }, 1024);
                }), 128))
              ]),
              _: 1
            })
          ]),
          _createElementVNode$2("div", _hoisted_5$1, [
            _createVNode$2(_component_v_row, {
              align: "center",
              "no-gutters": ""
            }, {
              default: _withCtx$2(() => [
                _createVNode$2(_component_v_col, {
                  cols: "2",
                  md: "1"
                }),
                _createVNode$2(_component_v_col, {
                  cols: "8",
                  md: "10",
                  class: "d-flex justify-center"
                }, {
                  default: _withCtx$2(() => [
                    _createVNode$2(_component_v_pagination, {
                      modelValue: pageHosts.value,
                      "onUpdate:modelValue": _cache[2] || (_cache[2] = ($event) => pageHosts.value = $event),
                      length: pageCountHosts.value,
                      "total-visible": "5",
                      rounded: "circle",
                      class: "d-none d-sm-flex my-0",
                      disabled: loading.value
                    }, null, 8, ["modelValue", "length", "disabled"]),
                    _createVNode$2(_component_v_pagination, {
                      modelValue: pageHosts.value,
                      "onUpdate:modelValue": _cache[3] || (_cache[3] = ($event) => pageHosts.value = $event),
                      length: pageCountHosts.value,
                      "total-visible": "0",
                      rounded: "circle",
                      class: "d-sm-none my-0",
                      disabled: loading.value
                    }, null, 8, ["modelValue", "length", "disabled"])
                  ]),
                  _: 1
                }),
                _createVNode$2(_component_v_col, {
                  cols: "2",
                  md: "1",
                  class: "d-flex justify-end"
                }, {
                  default: _withCtx$2(() => [
                    _createVNode$2(_component_v_menu, null, {
                      activator: _withCtx$2(({ props: props2 }) => [
                        _createVNode$2(_component_v_btn, _mergeProps$1(props2, {
                          icon: "",
                          rounded: "circle",
                          variant: "tonal",
                          disabled: loading.value
                        }), {
                          default: _withCtx$2(() => [
                            _createTextVNode$2(_toDisplayString$2(_unref$1(pageTitle)(itemsPerPageHosts.value)), 1)
                          ]),
                          _: 2
                        }, 1040, ["disabled"])
                      ]),
                      default: _withCtx$2(() => [
                        _createVNode$2(_component_v_list, null, {
                          default: _withCtx$2(() => [
                            (_openBlock$2(true), _createElementBlock$1(_Fragment$1, null, _renderList$1(_unref$1(itemsPerPageOptions), (item, index) => {
                              return _openBlock$2(), _createBlock$2(_component_v_list_item, {
                                key: index,
                                value: item.value,
                                onClick: ($event) => itemsPerPageHosts.value = item.value
                              }, {
                                default: _withCtx$2(() => [
                                  _createVNode$2(_component_v_list_item_title, null, {
                                    default: _withCtx$2(() => [
                                      _createTextVNode$2(_toDisplayString$2(item.title), 1)
                                    ]),
                                    _: 2
                                  }, 1024)
                                ]),
                                _: 2
                              }, 1032, ["value", "onClick"]);
                            }), 128))
                          ]),
                          _: 1
                        })
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                })
              ]),
              _: 1
            })
          ]),
          _createVNode$2(_component_v_divider)
        ]),
        hostDialogVisible.value ? (_openBlock$2(), _createBlock$2(_sfc_main$4, {
          key: 0,
          modelValue: hostDialogVisible.value,
          "onUpdate:modelValue": _cache[4] || (_cache[4] = ($event) => hostDialogVisible.value = $event),
          "initial-value": currentHost.value,
          "is-adding": isAdding.value,
          "best-cloudflare-i-ps": _ctx.bestCloudflareIPs,
          api: _ctx.api,
          onRefresh: _cache[5] || (_cache[5] = ($event) => emit("refresh")),
          onShowSnackbar: _cache[6] || (_cache[6] = (v) => emit("show-snackbar", v)),
          onShowError: _cache[7] || (_cache[7] = (v) => emit("show-error", v)),
          onClose: _cache[8] || (_cache[8] = ($event) => hostDialogVisible.value = false)
        }, null, 8, ["modelValue", "initial-value", "is-adding", "best-cloudflare-i-ps", "api"])) : _createCommentVNode$1("", true)
      ], 64);
    };
  }
});

const {defineComponent:_defineComponent$1} = await importShared('vue');

const {createTextVNode:_createTextVNode$1,resolveComponent:_resolveComponent$1,withCtx:_withCtx$1,createVNode:_createVNode$1,toDisplayString:_toDisplayString$1,createElementVNode:_createElementVNode$1,openBlock:_openBlock$1,createBlock:_createBlock$1} = await importShared('vue');

const _hoisted_1$1 = { class: "text-h6 mt-2 font-weight-bold" };
const _hoisted_2$1 = { class: "text-h6 mt-2 font-weight-bold" };
const _hoisted_3$1 = { class: "text-h6 mt-2 font-weight-bold" };
const _hoisted_4$1 = { class: "text-h6 mt-2 font-weight-bold" };
const _hoisted_5 = { class: "text-h6 mt-2 font-weight-bold" };
const _hoisted_6 = { class: "text-h6 mt-2 font-weight-bold" };
const _hoisted_7 = { class: "text-h6 mt-2 font-weight-bold" };
const _hoisted_8 = { class: "text-h6 mt-2 font-weight-bold" };
const _sfc_main$1 = /* @__PURE__ */ _defineComponent$1({
  __name: "StatisticsPanel",
  props: {
    rulesetRulesCount: {},
    topRulesCount: {},
    proxyGroupsCount: {},
    extraProxiesCount: {},
    extraRuleProvidersCount: {},
    hostsCount: {},
    geositeCount: {},
    lastUpdated: {}
  },
  setup(__props) {
    return (_ctx, _cache) => {
      const _component_v_icon = _resolveComponent$1("v-icon");
      const _component_v_card = _resolveComponent$1("v-card");
      const _component_v_col = _resolveComponent$1("v-col");
      const _component_v_row = _resolveComponent$1("v-row");
      return _openBlock$1(), _createBlock$1(_component_v_row, { dense: "" }, {
        default: _withCtx$1(() => [
          _createVNode$1(_component_v_col, {
            cols: "6",
            md: "3"
          }, {
            default: _withCtx$1(() => [
              _createVNode$1(_component_v_card, {
                class: "pa-4 d-flex flex-column align-center",
                rounded: "xl"
              }, {
                default: _withCtx$1(() => [
                  _createVNode$1(_component_v_icon, {
                    size: "40",
                    color: "primary"
                  }, {
                    default: _withCtx$1(() => _cache[0] || (_cache[0] = [
                      _createTextVNode$1("mdi-format-list-bulleted")
                    ])),
                    _: 1
                  }),
                  _createElementVNode$1("div", _hoisted_1$1, _toDisplayString$1(_ctx.rulesetRulesCount), 1),
                  _cache[1] || (_cache[1] = _createElementVNode$1("div", { class: "text-subtitle-2 grey--text" }, "规则集规则", -1))
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode$1(_component_v_col, {
            cols: "6",
            md: "3"
          }, {
            default: _withCtx$1(() => [
              _createVNode$1(_component_v_card, {
                class: "pa-4 d-flex flex-column align-center",
                rounded: "xl"
              }, {
                default: _withCtx$1(() => [
                  _createVNode$1(_component_v_icon, {
                    size: "40",
                    color: "info"
                  }, {
                    default: _withCtx$1(() => _cache[2] || (_cache[2] = [
                      _createTextVNode$1("mdi-pin")
                    ])),
                    _: 1
                  }),
                  _createElementVNode$1("div", _hoisted_2$1, _toDisplayString$1(_ctx.topRulesCount), 1),
                  _cache[3] || (_cache[3] = _createElementVNode$1("div", { class: "text-subtitle-2 grey--text" }, "置顶规则", -1))
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode$1(_component_v_col, {
            cols: "6",
            md: "3"
          }, {
            default: _withCtx$1(() => [
              _createVNode$1(_component_v_card, {
                class: "pa-4 d-flex flex-column align-center",
                rounded: "xl"
              }, {
                default: _withCtx$1(() => [
                  _createVNode$1(_component_v_icon, {
                    size: "40",
                    color: "success"
                  }, {
                    default: _withCtx$1(() => _cache[4] || (_cache[4] = [
                      _createTextVNode$1("mdi-source-branch")
                    ])),
                    _: 1
                  }),
                  _createElementVNode$1("div", _hoisted_3$1, _toDisplayString$1(_ctx.proxyGroupsCount), 1),
                  _cache[5] || (_cache[5] = _createElementVNode$1("div", { class: "text-subtitle-2 grey--text" }, "代理组", -1))
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode$1(_component_v_col, {
            cols: "6",
            md: "3"
          }, {
            default: _withCtx$1(() => [
              _createVNode$1(_component_v_card, {
                class: "pa-4 d-flex flex-column align-center",
                rounded: "xl"
              }, {
                default: _withCtx$1(() => [
                  _createVNode$1(_component_v_icon, {
                    size: "40",
                    color: "error"
                  }, {
                    default: _withCtx$1(() => _cache[6] || (_cache[6] = [
                      _createTextVNode$1("mdi-rocket-launch")
                    ])),
                    _: 1
                  }),
                  _createElementVNode$1("div", _hoisted_4$1, _toDisplayString$1(_ctx.extraProxiesCount), 1),
                  _cache[7] || (_cache[7] = _createElementVNode$1("div", { class: "text-subtitle-2 grey--text" }, "出站代理", -1))
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode$1(_component_v_col, {
            cols: "6",
            md: "3"
          }, {
            default: _withCtx$1(() => [
              _createVNode$1(_component_v_card, {
                class: "pa-4 d-flex flex-column align-center",
                rounded: "xl"
              }, {
                default: _withCtx$1(() => [
                  _createVNode$1(_component_v_icon, {
                    size: "40",
                    color: "warning"
                  }, {
                    default: _withCtx$1(() => _cache[8] || (_cache[8] = [
                      _createTextVNode$1("mdi-folder-multiple")
                    ])),
                    _: 1
                  }),
                  _createElementVNode$1("div", _hoisted_5, _toDisplayString$1(_ctx.extraRuleProvidersCount), 1),
                  _cache[9] || (_cache[9] = _createElementVNode$1("div", { class: "text-subtitle-2 grey--text" }, "规则集合", -1))
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode$1(_component_v_col, {
            cols: "6",
            md: "3"
          }, {
            default: _withCtx$1(() => [
              _createVNode$1(_component_v_card, {
                class: "pa-4 d-flex flex-column align-center",
                rounded: "xl"
              }, {
                default: _withCtx$1(() => [
                  _createVNode$1(_component_v_icon, {
                    size: "40",
                    color: "secondary"
                  }, {
                    default: _withCtx$1(() => _cache[10] || (_cache[10] = [
                      _createTextVNode$1("mdi-lan")
                    ])),
                    _: 1
                  }),
                  _createElementVNode$1("div", _hoisted_6, _toDisplayString$1(_ctx.hostsCount), 1),
                  _cache[11] || (_cache[11] = _createElementVNode$1("div", { class: "text-subtitle-2 grey--text" }, "Hosts", -1))
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode$1(_component_v_col, {
            cols: "6",
            md: "3"
          }, {
            default: _withCtx$1(() => [
              _createVNode$1(_component_v_card, {
                class: "pa-4 d-flex flex-column align-center",
                rounded: "xl"
              }, {
                default: _withCtx$1(() => [
                  _createVNode$1(_component_v_icon, {
                    size: "40",
                    color: "info"
                  }, {
                    default: _withCtx$1(() => _cache[12] || (_cache[12] = [
                      _createTextVNode$1("mdi-earth")
                    ])),
                    _: 1
                  }),
                  _createElementVNode$1("div", _hoisted_7, _toDisplayString$1(_ctx.geositeCount), 1),
                  _cache[13] || (_cache[13] = _createElementVNode$1("div", { class: "text-subtitle-2 grey--text" }, "Geosite", -1))
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode$1(_component_v_col, {
            cols: "6",
            md: "3"
          }, {
            default: _withCtx$1(() => [
              _createVNode$1(_component_v_card, {
                class: "pa-4 d-flex flex-column align-center",
                rounded: "xl"
              }, {
                default: _withCtx$1(() => [
                  _createVNode$1(_component_v_icon, {
                    size: "40",
                    color: "success"
                  }, {
                    default: _withCtx$1(() => _cache[14] || (_cache[14] = [
                      _createTextVNode$1("mdi-clock-time-four-outline")
                    ])),
                    _: 1
                  }),
                  _createElementVNode$1("div", _hoisted_8, _toDisplayString$1(_ctx.lastUpdated), 1),
                  _cache[15] || (_cache[15] = _createElementVNode$1("div", { class: "text-subtitle-2 grey--text" }, "最后更新", -1))
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _: 1
      });
    };
  }
});

const {defineComponent:_defineComponent} = await importShared('vue');

const {toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,unref:_unref,createElementVNode:_createElementVNode,createVNode:_createVNode,createElementBlock:_createElementBlock,mergeProps:_mergeProps,renderList:_renderList,Fragment:_Fragment} = await importShared('vue');

const _hoisted_1 = { class: "plugin-page" };
const _hoisted_2 = ["src"];
const _hoisted_3 = { key: 1 };
const _hoisted_4 = { key: 0 };
const {ref,onMounted,computed} = await importShared('vue');
const _sfc_main = /* @__PURE__ */ _defineComponent({
  __name: "Page",
  props: {
    model: {
      type: Object,
      default: () => {
      }
    },
    api: {
      type: Object,
      default: () => {
      }
    }
  },
  emits: ["action", "switch", "close"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const activeTab = ref(0);
    const snackbar = ref({
      show: false,
      message: "",
      color: "success"
    });
    const customOutbounds = ref([]);
    const subUrl = ref("");
    const proxyGroups = ref([]);
    const proxyProviders = ref([]);
    const proxies = ref([]);
    const presetIdentifiers = ref([]);
    const expand = ref(false);
    const loading = ref(true);
    const error = ref(false);
    const errorMsg = ref("");
    const rules = ref([]);
    const rulesetRules = ref([]);
    const ruleProviders = ref([]);
    const hosts = ref([]);
    const status = ref("running");
    const rulesetPrefix = ref("📂<=");
    const geoRules = ref({
      geoip: [],
      geosite: []
    });
    const lastUpdated = ref("");
    const showYamlDialog = ref(false);
    const displayedYaml = ref("");
    const visibilityDialogVisible = ref(false);
    const currentVisibilityMeta = ref({ ...defaultMetadata });
    const currentVisibilityEndpoint = ref("");
    const currentVisibilityRegion = ref("");
    const sortedRules = computed(
      () => [...rules.value].sort((a, b) => a.priority - b.priority)
    );
    const sortedRulesetRules = computed(
      () => [...rulesetRules.value].sort((a, b) => a.priority - b.priority)
    );
    const ruleProviderNames = computed(() => {
      return ruleProviders.value.map((provider) => provider.name);
    });
    const subscriptionsInfo = ref({});
    const bestCloudflareIPs = ref([]);
    function copyToClipboard(text) {
      navigator.clipboard.writeText(text).then(() => {
        snackbar.value = {
          show: true,
          message: "已复制到剪贴板",
          color: "success"
        };
      }).catch(() => {
        snackbar.value = {
          show: true,
          message: "复制失败",
          color: "error"
        };
      });
    }
    function copyPluginLink() {
      const url = `${window.location.origin}/#/plugins?tab=installed&id=ClashRuleProvider`;
      copyToClipboard(url);
    }
    function generateIdentifierUrl(identifier) {
      if (!subUrl.value) return "";
      try {
        const url = new URL(subUrl.value, window.location.origin);
        url.searchParams.set("identifier", identifier);
        return url.toString();
      } catch (e) {
        console.error("Failed to parse URL", e);
        return subUrl.value;
      }
    }
    function showYaml(obj) {
      displayedYaml.value = jsYaml.dump(obj);
      showYamlDialog.value = true;
    }
    function showError(Msg) {
      error.value = true;
      errorMsg.value = Msg;
    }
    function handleEditVisibility(meta, endpoint, region) {
      currentVisibilityMeta.value = meta;
      currentVisibilityEndpoint.value = endpoint;
      currentVisibilityRegion.value = region;
      visibilityDialogVisible.value = true;
    }
    async function refreshStatus() {
      const state = await props.api.get("/plugin/ClashRuleProvider/status");
      status.value = state?.data?.state ? "running" : "disabled";
      subUrl.value = state?.data?.sub_url || "";
      if (state?.data?.subscription_info) {
        subscriptionsInfo.value = state.data.subscription_info;
      }
      bestCloudflareIPs.value = state?.data?.best_cf_ip || [];
      rulesetPrefix.value = state?.data?.ruleset_prefix || "📂<=";
      geoRules.value = state?.data?.geoRules ?? geoRules.value;
    }
    async function refreshTopRules() {
      const response = await props.api.get("/plugin/ClashRuleProvider/rules/top");
      rules.value = response?.data || [];
    }
    async function refreshRulesetRules() {
      const response = await props.api.get("/plugin/ClashRuleProvider/rules/ruleset");
      rulesetRules.value = response?.data || [];
    }
    async function refreshOutbounds() {
      const outboundsResponse = await props.api.get("/plugin/ClashRuleProvider/clash-outbound");
      customOutbounds.value = outboundsResponse?.data || [];
    }
    async function refreshExtraRuleProviders() {
      const providersResponse = await props.api.get("/plugin/ClashRuleProvider/rule-providers");
      ruleProviders.value = providersResponse?.data || [];
    }
    async function refreshProxyGroups() {
      const proxyGroupsResponse = await props.api.get("/plugin/ClashRuleProvider/proxy-groups");
      proxyGroups.value = proxyGroupsResponse?.data || [];
    }
    async function refreshExtraProxies() {
      const extraProxiesResponse = await props.api.get("/plugin/ClashRuleProvider/proxies");
      proxies.value = extraProxiesResponse?.data || [];
    }
    async function refreshHosts() {
      const hostsResponse = await props.api.get("/plugin/ClashRuleProvider/hosts");
      hosts.value = hostsResponse?.data || [];
    }
    async function refreshProxyProviders() {
      const proxyProvidersResponse = await props.api.get("/plugin/ClashRuleProvider/proxy-providers");
      proxyProviders.value = proxyProvidersResponse?.data || [];
    }
    async function refreshDataOf(region) {
      switch (region) {
        case "status":
          return refreshStatus();
        case "top":
          return refreshTopRules();
        case "ruleset":
          return refreshRulesetRules();
        case "clash-outbounds":
          return refreshOutbounds();
        case "rule-providers":
          return refreshExtraRuleProviders();
        case "proxy-groups":
          return refreshProxyGroups();
        case "proxies":
          return refreshExtraProxies();
        case "hosts":
          return refreshHosts();
        case "proxy-providers":
          return refreshProxyProviders();
        default:
          throw new Error("Unknown region: " + region);
      }
    }
    async function refreshAllRegions(regions) {
      try {
        await Promise.all(regions.map(refreshDataOf));
      } catch (err) {
        console.error("获取数据失败:", err);
        if (err instanceof Error) {
          showError(err.message || "获取数据失败");
        }
        status.value = "error";
      } finally {
        lastUpdated.value = (/* @__PURE__ */ new Date()).toLocaleString();
      }
    }
    async function refreshData() {
      loading.value = true;
      error.value = false;
      errorMsg.value = "";
      try {
        const [
          state,
          response,
          response_ruleset,
          outboundsResponse,
          providersResponse,
          proxyGroupsResponse,
          extraProxiesResponse,
          hostsResponse,
          proxyProvidersResponse
        ] = await Promise.all([
          props.api.get("/plugin/ClashRuleProvider/status"),
          props.api.get("/plugin/ClashRuleProvider/rules/top"),
          props.api.get("/plugin/ClashRuleProvider/rules/ruleset"),
          props.api.get("/plugin/ClashRuleProvider/clash-outbound"),
          props.api.get("/plugin/ClashRuleProvider/rule-providers"),
          props.api.get("/plugin/ClashRuleProvider/proxy-groups"),
          props.api.get("/plugin/ClashRuleProvider/proxies"),
          props.api.get("/plugin/ClashRuleProvider/hosts"),
          props.api.get("/plugin/ClashRuleProvider/proxy-providers")
        ]);
        status.value = state?.data?.state ? "running" : "disabled";
        subUrl.value = state?.data?.sub_url || "";
        if (state?.data?.subscription_info) {
          subscriptionsInfo.value = state.data.subscription_info;
        }
        bestCloudflareIPs.value = state?.data?.best_cf_ip || [];
        rulesetPrefix.value = state?.data?.ruleset_prefix || "📂<=";
        geoRules.value = state?.data?.geoRules ?? geoRules.value;
        presetIdentifiers.value = state?.data?.preset_identifiers || [];
        rules.value = response?.data || [];
        rulesetRules.value = response_ruleset?.data || [];
        customOutbounds.value = outboundsResponse?.data || [];
        ruleProviders.value = providersResponse?.data || [];
        proxyGroups.value = proxyGroupsResponse?.data || [];
        proxies.value = extraProxiesResponse?.data || [];
        hosts.value = hostsResponse?.data || [];
        proxyProviders.value = proxyProvidersResponse?.data || [];
        lastUpdated.value = (/* @__PURE__ */ new Date()).toLocaleString();
      } catch (err) {
        console.error("获取数据失败:", err);
        if (err instanceof Error) {
          showError(err.message || "获取数据失败");
        }
        status.value = "error";
      } finally {
        loading.value = false;
      }
    }
    function notifySwitch() {
      emit("switch");
    }
    function notifyClose() {
      emit("close");
    }
    onMounted(() => {
      refreshData();
    });
    return (_ctx, _cache) => {
      const _component_v_alert = _resolveComponent("v-alert");
      const _component_v_icon = _resolveComponent("v-icon");
      const _component_v_chip = _resolveComponent("v-chip");
      const _component_v_card_title = _resolveComponent("v-card-title");
      const _component_v_btn = _resolveComponent("v-btn");
      const _component_v_card_item = _resolveComponent("v-card-item");
      const _component_v_skeleton_loader = _resolveComponent("v-skeleton-loader");
      const _component_v_tab = _resolveComponent("v-tab");
      const _component_v_tabs = _resolveComponent("v-tabs");
      const _component_v_window_item = _resolveComponent("v-window-item");
      const _component_v_window = _resolveComponent("v-window");
      const _component_v_card_text = _resolveComponent("v-card-text");
      const _component_v_expand_transition = _resolveComponent("v-expand-transition");
      const _component_v_list_item_title = _resolveComponent("v-list-item-title");
      const _component_v_list_item = _resolveComponent("v-list-item");
      const _component_v_list = _resolveComponent("v-list");
      const _component_v_menu = _resolveComponent("v-menu");
      const _component_v_spacer = _resolveComponent("v-spacer");
      const _component_v_card_actions = _resolveComponent("v-card-actions");
      const _component_v_snackbar = _resolveComponent("v-snackbar");
      const _component_v_card = _resolveComponent("v-card");
      return _openBlock(), _createElementBlock("div", _hoisted_1, [
        _createVNode(_component_v_card, null, {
          default: _withCtx(() => [
            error.value ? (_openBlock(), _createBlock(_component_v_alert, {
              key: 0,
              modelValue: error.value,
              "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => error.value = $event),
              type: "error",
              class: "mb-4",
              closable: ""
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(errorMsg.value), 1)
              ]),
              _: 1
            }, 8, ["modelValue"])) : _createCommentVNode("", true),
            _createVNode(_component_v_card_item, null, {
              append: _withCtx(() => [
                _createVNode(_component_v_btn, {
                  icon: "",
                  color: "primary",
                  variant: "text",
                  onClick: notifyClose
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, { left: "" }, {
                      default: _withCtx(() => _cache[18] || (_cache[18] = [
                        _createTextVNode("mdi-close")
                      ])),
                      _: 1
                    })
                  ]),
                  _: 1
                })
              ]),
              default: _withCtx(() => [
                _createVNode(_component_v_card_title, null, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, {
                      class: "mr-2",
                      size: "24"
                    }, {
                      default: _withCtx(() => [
                        _createElementVNode("img", {
                          src: `/api/v1/plugin/file/clashruleprovider/dist${_unref(MetaLogo)}`,
                          alt: "icon",
                          style: { "width": "100%", "height": "100%" }
                        }, null, 8, _hoisted_2)
                      ]),
                      _: 1
                    }),
                    _cache[17] || (_cache[17] = _createTextVNode(" Clash Rule Provider ")),
                    _createVNode(_component_v_chip, {
                      size: "small",
                      color: status.value === "running" ? "success" : "warning",
                      onClick: copyPluginLink
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(status.value), 1)
                      ]),
                      _: 1
                    }, 8, ["color"])
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createVNode(_component_v_card_text, null, {
              default: _withCtx(() => [
                loading.value ? (_openBlock(), _createBlock(_component_v_skeleton_loader, {
                  key: 0,
                  type: "card"
                })) : (_openBlock(), _createElementBlock("div", _hoisted_3, [
                  _createVNode(_component_v_tabs, {
                    modelValue: activeTab.value,
                    "onUpdate:modelValue": _cache[1] || (_cache[1] = ($event) => activeTab.value = $event),
                    "background-color": "primary",
                    dark: ""
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_tab, null, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_icon, { start: "" }, {
                            default: _withCtx(() => _cache[19] || (_cache[19] = [
                              _createTextVNode("mdi-format-list-bulleted")
                            ])),
                            _: 1
                          }),
                          _cache[20] || (_cache[20] = _createTextVNode(" 规则集规则 "))
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_tab, null, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_icon, { start: "" }, {
                            default: _withCtx(() => _cache[21] || (_cache[21] = [
                              _createTextVNode("mdi-pin")
                            ])),
                            _: 1
                          }),
                          _cache[22] || (_cache[22] = _createTextVNode(" 置顶规则 "))
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_tab, null, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_icon, { start: "" }, {
                            default: _withCtx(() => _cache[23] || (_cache[23] = [
                              _createTextVNode("mdi-source-branch")
                            ])),
                            _: 1
                          }),
                          _cache[24] || (_cache[24] = _createTextVNode(" 代理组 "))
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_tab, null, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_icon, { start: "" }, {
                            default: _withCtx(() => _cache[25] || (_cache[25] = [
                              _createTextVNode("mdi-rocket-launch")
                            ])),
                            _: 1
                          }),
                          _cache[26] || (_cache[26] = _createTextVNode(" 出站代理 "))
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_tab, null, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_icon, { start: "" }, {
                            default: _withCtx(() => _cache[27] || (_cache[27] = [
                              _createTextVNode("mdi-folder-multiple")
                            ])),
                            _: 1
                          }),
                          _cache[28] || (_cache[28] = _createTextVNode(" 规则集合 "))
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_tab, null, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_icon, { start: "" }, {
                            default: _withCtx(() => _cache[29] || (_cache[29] = [
                              _createTextVNode("mdi-lan")
                            ])),
                            _: 1
                          }),
                          _cache[30] || (_cache[30] = _createTextVNode(" Hosts "))
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_tab, null, {
                        default: _withCtx(() => [
                          _createVNode(_component_v_icon, { start: "" }, {
                            default: _withCtx(() => _cache[31] || (_cache[31] = [
                              _createTextVNode("mdi-cloud-sync")
                            ])),
                            _: 1
                          }),
                          _cache[32] || (_cache[32] = _createTextVNode(" 订阅状态 "))
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }, 8, ["modelValue"]),
                  _createVNode(_component_v_window, {
                    modelValue: activeTab.value,
                    "onUpdate:modelValue": _cache[10] || (_cache[10] = ($event) => activeTab.value = $event)
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_v_window_item, null, {
                        default: _withCtx(() => [
                          _createVNode(_sfc_main$q, {
                            rules: sortedRulesetRules.value,
                            "ruleset-prefix": rulesetPrefix.value,
                            api: __props.api,
                            "rule-provider-names": ruleProviderNames.value,
                            "geo-rules": geoRules.value,
                            "custom-outbounds": customOutbounds.value,
                            onRefresh: refreshAllRegions,
                            onShowSnackbar: _cache[2] || (_cache[2] = (val) => snackbar.value = val),
                            onShowError: showError
                          }, null, 8, ["rules", "ruleset-prefix", "api", "rule-provider-names", "geo-rules", "custom-outbounds"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_window_item, null, {
                        default: _withCtx(() => [
                          _createVNode(_sfc_main$n, {
                            rules: sortedRules.value,
                            api: __props.api,
                            "rule-provider-names": ruleProviderNames.value,
                            "geo-rules": geoRules.value,
                            "custom-outbounds": customOutbounds.value,
                            onRefresh: refreshAllRegions,
                            onShowSnackbar: _cache[3] || (_cache[3] = (val) => snackbar.value = val),
                            onShowError: showError,
                            onEditVisibility: handleEditVisibility
                          }, null, 8, ["rules", "api", "rule-provider-names", "geo-rules", "custom-outbounds"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_window_item, null, {
                        default: _withCtx(() => [
                          _createVNode(_sfc_main$i, {
                            "proxy-groups": proxyGroups.value,
                            "proxy-providers": proxyProviders.value,
                            "custom-outbounds": customOutbounds.value,
                            api: __props.api,
                            onRefresh: refreshAllRegions,
                            onShowSnackbar: _cache[4] || (_cache[4] = (val) => snackbar.value = val),
                            onShowError: showError,
                            onShowYaml: showYaml,
                            onCopyToClipboard: copyToClipboard,
                            onEditVisibility: handleEditVisibility
                          }, null, 8, ["proxy-groups", "proxy-providers", "custom-outbounds", "api"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_window_item, null, {
                        default: _withCtx(() => [
                          _createVNode(_sfc_main$d, {
                            proxies: proxies.value,
                            api: __props.api,
                            onRefresh: refreshAllRegions,
                            onShowSnackbar: _cache[5] || (_cache[5] = (val) => snackbar.value = val),
                            onShowError: showError,
                            onShowYaml: showYaml,
                            onCopyToClipboard: copyToClipboard,
                            onEditVisibility: handleEditVisibility
                          }, null, 8, ["proxies", "api"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_window_item, null, {
                        default: _withCtx(() => [
                          _createVNode(_sfc_main$6, {
                            "rule-providers": ruleProviders.value,
                            api: __props.api,
                            onRefresh: refreshAllRegions,
                            onShowSnackbar: _cache[6] || (_cache[6] = (val) => snackbar.value = val),
                            onShowError: showError,
                            onShowYaml: showYaml,
                            onEditVisibility: handleEditVisibility
                          }, null, 8, ["rule-providers", "api"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_window_item, null, {
                        default: _withCtx(() => [
                          _createVNode(_sfc_main$2, {
                            hosts: hosts.value,
                            "best-cloudflare-i-ps": bestCloudflareIPs.value,
                            api: __props.api,
                            onRefresh: _cache[7] || (_cache[7] = ($event) => refreshAllRegions(["hosts"])),
                            onShowSnackbar: _cache[8] || (_cache[8] = (val) => snackbar.value = val),
                            onShowError: showError
                          }, null, 8, ["hosts", "best-cloudflare-i-ps", "api"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_v_window_item, null, {
                        default: _withCtx(() => [
                          _createVNode(SubscriptionTab, {
                            "subscriptions-info": subscriptionsInfo.value,
                            api: __props.api,
                            onRefresh: refreshAllRegions,
                            onShowSnackbar: _cache[9] || (_cache[9] = (val) => snackbar.value = val),
                            onShowError: showError,
                            onCopyToClipboard: copyToClipboard,
                            onSwitch: notifySwitch
                          }, null, 8, ["subscriptions-info", "api"])
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }, 8, ["modelValue"])
                ]))
              ]),
              _: 1
            }),
            _createVNode(_component_v_expand_transition, null, {
              default: _withCtx(() => [
                expand.value ? (_openBlock(), _createElementBlock("div", _hoisted_4, [
                  _createVNode(_sfc_main$1, {
                    "ruleset-rules-count": sortedRulesetRules.value.length,
                    "top-rules-count": sortedRules.value.length,
                    "proxy-groups-count": proxyGroups.value.length,
                    "extra-proxies-count": proxies.value.length,
                    "extra-rule-providers-count": ruleProviders.value.length,
                    "hosts-count": hosts.value.length,
                    "geosite-count": geoRules.value.geosite.length,
                    "last-updated": lastUpdated.value
                  }, null, 8, ["ruleset-rules-count", "top-rules-count", "proxy-groups-count", "extra-proxies-count", "extra-rule-providers-count", "hosts-count", "geosite-count", "last-updated"])
                ])) : _createCommentVNode("", true)
              ]),
              _: 1
            }),
            _createVNode(_component_v_card_actions, null, {
              default: _withCtx(() => [
                _createVNode(_component_v_btn, {
                  color: "primary",
                  loading: loading.value,
                  onClick: refreshData
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, { left: "" }, {
                      default: _withCtx(() => _cache[33] || (_cache[33] = [
                        _createTextVNode("mdi-refresh")
                      ])),
                      _: 1
                    }),
                    _cache[34] || (_cache[34] = _createTextVNode(" 刷新数据 "))
                  ]),
                  _: 1
                }, 8, ["loading"]),
                presetIdentifiers.value.length > 0 ? (_openBlock(), _createBlock(_component_v_menu, { key: 0 }, {
                  activator: _withCtx(({ props: props2 }) => [
                    _createVNode(_component_v_btn, _mergeProps({ color: "info" }, props2), {
                      default: _withCtx(() => [
                        _createVNode(_component_v_icon, { left: "" }, {
                          default: _withCtx(() => _cache[35] || (_cache[35] = [
                            _createTextVNode("mdi-link-variant")
                          ])),
                          _: 1
                        }),
                        _cache[36] || (_cache[36] = _createTextVNode(" 生成链接 "))
                      ]),
                      _: 2
                    }, 1040)
                  ]),
                  default: _withCtx(() => [
                    _createVNode(_component_v_list, null, {
                      default: _withCtx(() => [
                        _createVNode(_component_v_list_item, {
                          href: subUrl.value,
                          target: "_blank"
                        }, {
                          prepend: _withCtx(() => [
                            _createVNode(_component_v_icon, { icon: "mdi-link-variant" })
                          ]),
                          default: _withCtx(() => [
                            _createVNode(_component_v_list_item_title, null, {
                              default: _withCtx(() => _cache[37] || (_cache[37] = [
                                _createTextVNode("默认")
                              ])),
                              _: 1
                            })
                          ]),
                          _: 1
                        }, 8, ["href"]),
                        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(presetIdentifiers.value, (id) => {
                          return _openBlock(), _createBlock(_component_v_list_item, {
                            key: id,
                            href: generateIdentifierUrl(id),
                            target: "_blank"
                          }, {
                            prepend: _withCtx(() => [
                              _createVNode(_component_v_icon, { icon: "mdi-devices" })
                            ]),
                            default: _withCtx(() => [
                              _createVNode(_component_v_list_item_title, null, {
                                default: _withCtx(() => [
                                  _createTextVNode(_toDisplayString(id), 1)
                                ]),
                                _: 2
                              }, 1024)
                            ]),
                            _: 2
                          }, 1032, ["href"]);
                        }), 128))
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                })) : (_openBlock(), _createBlock(_component_v_btn, {
                  key: 1,
                  color: "info",
                  href: subUrl.value,
                  target: "_blank"
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, { left: "" }, {
                      default: _withCtx(() => _cache[38] || (_cache[38] = [
                        _createTextVNode("mdi-link-variant")
                      ])),
                      _: 1
                    }),
                    _cache[39] || (_cache[39] = _createTextVNode(" 生成链接 "))
                  ]),
                  _: 1
                }, 8, ["href"])),
                _createVNode(_component_v_btn, {
                  color: "success",
                  onClick: _cache[11] || (_cache[11] = ($event) => expand.value = !expand.value)
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, { left: "" }, {
                      default: _withCtx(() => _cache[40] || (_cache[40] = [
                        _createTextVNode("mdi-chart-bar")
                      ])),
                      _: 1
                    }),
                    _cache[41] || (_cache[41] = _createTextVNode(" 统计信息 "))
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_spacer),
                _createVNode(_component_v_btn, {
                  color: "primary",
                  onClick: notifySwitch
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_icon, { left: "" }, {
                      default: _withCtx(() => _cache[42] || (_cache[42] = [
                        _createTextVNode("mdi-cog")
                      ])),
                      _: 1
                    }),
                    _cache[43] || (_cache[43] = _createTextVNode(" 配置 "))
                  ]),
                  _: 1
                })
              ]),
              _: 1
            }),
            _createVNode(_component_v_snackbar, {
              modelValue: snackbar.value.show,
              "onUpdate:modelValue": _cache[12] || (_cache[12] = ($event) => snackbar.value.show = $event),
              color: snackbar.value.color,
              location: "bottom",
              class: "mb-2"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(snackbar.value.message), 1)
              ]),
              _: 1
            }, 8, ["modelValue", "color"])
          ]),
          _: 1
        }),
        showYamlDialog.value ? (_openBlock(), _createBlock(_sfc_main$w, {
          key: 0,
          content: displayedYaml.value,
          onCopyToClipboard: copyToClipboard,
          onClose: _cache[13] || (_cache[13] = ($event) => showYamlDialog.value = false)
        }, null, 8, ["content"])) : _createCommentVNode("", true),
        visibilityDialogVisible.value ? (_openBlock(), _createBlock(_sfc_main$v, {
          key: 1,
          modelValue: visibilityDialogVisible.value,
          "onUpdate:modelValue": _cache[14] || (_cache[14] = ($event) => visibilityDialogVisible.value = $event),
          meta: currentVisibilityMeta.value,
          endpoint: currentVisibilityEndpoint.value,
          region: currentVisibilityRegion.value,
          api: __props.api,
          "preset-identifiers": presetIdentifiers.value,
          onRefresh: refreshAllRegions,
          onShowSnackbar: _cache[15] || (_cache[15] = (val) => snackbar.value = val),
          onShowError: showError,
          onClose: _cache[16] || (_cache[16] = ($event) => visibilityDialogVisible.value = false)
        }, null, 8, ["modelValue", "meta", "endpoint", "region", "api", "preset-identifiers"])) : _createCommentVNode("", true)
      ]);
    };
  }
});

const PageComponent = /* @__PURE__ */ _export_sfc(_sfc_main, [["__scopeId", "data-v-ab912b83"]]);

export { PageComponent as default };
