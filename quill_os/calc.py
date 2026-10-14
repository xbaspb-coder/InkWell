"""The Quill calculator engine: a small recursive-descent parser (no eval).

It follows the original JavaScript engine exactly, including JavaScript number
behaviour (division by zero gives Infinity, Math.round rounds halves upwards,
NaN instead of exceptions) and JavaScript-style number formatting.
"""

import math
import re
from decimal import Decimal, ROUND_HALF_UP

INF = float('inf')
NAN = float('nan')


class CalcError(Exception):
    pass


# ------------------------------------------------------------ JS number maths

def _safe(fn):
    """Call a math function the way JavaScript would: NaN/Infinity, never raise."""
    def wrapped(*a):
        try:
            return fn(*a)
        except OverflowError:
            return INF
        except (ValueError, ZeroDivisionError):
            return NAN
    return wrapped


def js_div(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        if a == 0 or math.isnan(a):
            return NAN
        neg = (a < 0) != (math.copysign(1.0, b) < 0)
        return -INF if neg else INF


def js_mod(a, b):
    if b == 0 or math.isinf(a) or math.isnan(a) or math.isnan(b):
        return NAN
    if math.isinf(b):
        return a
    return math.fmod(a, b)


def js_pow(a, b):
    if math.isnan(b):
        return NAN
    if b == 0:
        return 1.0
    if math.isnan(a):
        return NAN
    if abs(a) == 1 and math.isinf(b):
        return NAN
    if a == 0 and b < 0:
        odd = float(b).is_integer() and int(b) % 2 == 1
        return -INF if (odd and math.copysign(1.0, a) < 0) else INF
    try:
        return math.pow(a, b)
    except OverflowError:
        if a < 0 and float(b).is_integer() and int(b) % 2 == 1:
            return -INF
        return INF
    except ValueError:
        return NAN


def _log(x, base=None):
    if math.isnan(x) or x < 0:
        return NAN
    if x == 0:
        return -INF
    if math.isinf(x):
        return INF
    if base == 10:
        return math.log10(x)
    if base == 2:
        return math.log2(x)
    return math.log(x)


def _int_op(fn):
    def wrapped(x):
        if math.isnan(x) or math.isinf(x):
            return x
        return float(fn(x))
    return wrapped


def js_round(x):
    if math.isnan(x) or math.isinf(x):
        return x
    return float(math.floor(x + 0.5))


def js_sign(x):
    if math.isnan(x):
        return NAN
    return 1.0 if x > 0 else -1.0 if x < 0 else x


def js_cbrt(x):
    if hasattr(math, 'cbrt'):
        return math.cbrt(x)
    if math.isnan(x) or math.isinf(x) or x == 0:
        return x
    return math.copysign(abs(x) ** (1.0 / 3.0), x)


def js_min(*a):
    if not a:
        return INF
    if any(math.isnan(x) for x in a):
        return NAN
    return min(a)


def js_max(*a):
    if not a:
        return -INF
    if any(math.isnan(x) for x in a):
        return NAN
    return max(a)


def _num_arg(args, i):
    """JavaScript passes undefined (→ NaN) for missing arguments."""
    return args[i] if i < len(args) else NAN


# ------------------------------------------------------------ the parser

_TOKEN = re.compile(r'\s*(?:([0-9]+\.?[0-9]*(?:e[+-]?[0-9]+)?|\.[0-9]+(?:e[+-]?[0-9]+)?)|([a-z_][a-z0-9_]*)|(.))', re.S)


def _tokenize(s):
    toks = []
    pos = 0
    while pos < len(s):
        m = _TOKEN.match(s, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
        if m.group(1) is not None:
            toks.append(('n', float(m.group(1))))
        elif m.group(2) is not None:
            toks.append(('i', m.group(2).lower()))
        elif m.group(3) is not None and m.group(3) != ' ':
            toks.append(('o', m.group(3)))
        elif m.group(3) is None and m.group(0).strip() == '':
            break
    return toks


def _show(v):
    """How a token value appears in an error message (JS string conversion)."""
    if isinstance(v, float):
        return js_number_to_string(v)
    return str(v)


def calc_eval(src, deg=False):
    s = str(src).replace('×', '*').replace('÷', '/').replace('−', '-').replace('π', 'pi').replace('√', 'sqrt')
    s = re.sub(r'\s+', ' ', s)
    toks = _tokenize(s)
    p = [0]

    def peek():
        return toks[p[0]] if p[0] < len(toks) else None

    def nxt():
        t = peek()
        p[0] += 1
        return t

    def err(msg):
        raise CalcError(msg)

    consts = {'pi': math.pi, 'e': math.e, 'tau': math.pi * 2, 'phi': (1 + math.sqrt(5)) / 2}

    def to_rad(x):
        return x * math.pi / 180 if deg else x

    def from_rad(x):
        return x * 180 / math.pi if deg else x

    def fact(n):
        if math.isnan(n) or n < 0 or math.isinf(n) or n != math.floor(n):
            err('Factorial needs a whole number')
        if n > 170:
            return INF
        r = 1.0
        for i in range(2, int(n) + 1):
            r *= i
        return r

    def sqrt(x):
        if x < 0:
            err('Square root of a negative number')
        return math.sqrt(x) if not math.isnan(x) else NAN

    f1 = lambda fn: (lambda *a: fn(_num_arg(a, 0)))  # noqa: E731
    fns = {
        'sin': f1(lambda x: _safe(math.sin)(to_rad(x))),
        'cos': f1(lambda x: _safe(math.cos)(to_rad(x))),
        'tan': f1(lambda x: _safe(math.tan)(to_rad(x))),
        'asin': f1(lambda x: from_rad(_safe(math.asin)(x))),
        'acos': f1(lambda x: from_rad(_safe(math.acos)(x))),
        'atan': f1(lambda x: from_rad(_safe(math.atan)(x))),
        'sinh': f1(_safe(math.sinh)), 'cosh': f1(_safe(math.cosh)), 'tanh': f1(_safe(math.tanh)),
        'sqrt': f1(sqrt), 'cbrt': f1(js_cbrt),
        'ln': f1(lambda x: _log(x)), 'log': f1(lambda x: _log(x, 10)), 'log2': f1(lambda x: _log(x, 2)),
        'exp': f1(_safe(math.exp)), 'abs': f1(abs),
        'floor': f1(_int_op(math.floor)), 'ceil': f1(_int_op(math.ceil)), 'round': f1(js_round),
        'sign': f1(js_sign), 'fact': f1(fact), 'min': js_min, 'max': js_max,
        'pow': lambda *a: js_pow(_num_arg(a, 0), _num_arg(a, 1)),
        'mod': lambda *a: js_mod(_num_arg(a, 0), _num_arg(a, 1)),
        'rad': f1(lambda x: x * math.pi / 180), 'deg': f1(lambda x: x * 180 / math.pi),
    }

    def expr():
        v = term()
        while True:
            t = peek()
            if t and t[0] == 'o' and t[1] in ('+', '-'):
                nxt()
                r = term()
                v = v + r if t[1] == '+' else v - r
            else:
                return v

    def starts_primary(t):
        return t is not None and (t[0] == 'n' or t[0] == 'i' or (t[0] == 'o' and t[1] == '('))

    def term():
        v = unary()
        while True:
            t = peek()
            if t and t[0] == 'o' and t[1] in ('*', '/'):
                nxt()
                r = unary()
                v = v * r if t[1] == '*' else js_div(v, r)
            elif t and t[0] == 'i' and t[1] == 'mod':
                nxt()
                v = js_mod(v, unary())
            elif starts_primary(t) and not (t[0] == 'i' and t[1] == 'mod'):
                v = v * unary()
            else:
                return v

    def unary():
        t = peek()
        if t and t[0] == 'o' and t[1] == '-':
            nxt()
            return -unary()
        if t and t[0] == 'o' and t[1] == '+':
            nxt()
            return unary()
        return power()

    def power():
        b = postfix()
        t = peek()
        nx = toks[p[0] + 1] if p[0] + 1 < len(toks) else None
        if t and t[0] == 'o' and (t[1] == '^' or (t[1] == '*' and nx is not None and nx[1] == '*')):
            if t[1] == '*':
                p[0] += 1
            nxt()
            return js_pow(b, unary())
        return b

    def postfix():
        v = primary()
        while True:
            t = peek()
            if t and t[0] == 'o' and t[1] == '!':
                nxt()
                v = fact(v)
            elif t and t[0] == 'o' and t[1] == '%':
                nxt()
                v = v / 100
            else:
                return v

    def primary():
        t = nxt()
        if t is None:
            err('Unexpected end')
        if t[0] == 'n':
            return t[1]
        if t[0] == 'o' and t[1] == '(':
            v = expr()
            c = nxt()
            if c is None or c[1] != ')':
                err('Missing )')
            return v
        if t[0] == 'i':
            if t[1] in consts:
                return consts[t[1]]
            if t[1] in fns:
                o = nxt()
                if o is None or o[1] != '(':
                    err('Use ' + t[1] + '(…)')
                args = []
                if peek() is not None and peek()[1] == ')':
                    nxt()
                else:
                    while True:
                        args.append(expr())
                        c = nxt()
                        if c is None:
                            err('Missing )')
                        if c[1] == ')':
                            break
                        if c[1] != ',':
                            err('Unexpected ' + _show(c[1]))
                return fns[t[1]](*args)
            err('Unknown name “' + t[1] + '”')
        err('Unexpected “' + _show(t[1]) + '”')

    if not toks:
        err('Empty')
    v = expr()
    if p[0] < len(toks):
        err('Unexpected “' + _show(toks[p[0]][1]) + '”')
    return float(v)


# ------------------------------------------------------------ JS number text

def _shortest_digits(x):
    """Digits and decimal exponent of the shortest round-trip form of |x|.

    Returns (digits, n) meaning 0.digits × 10^n, as in the ECMAScript spec.
    """
    d = Decimal(repr(abs(x))).normalize()
    sign, digs, exp = d.as_tuple()
    digits = ''.join(map(str, digs)).rstrip('0') or '0'
    n = len(digs) + exp
    return digits, n


def js_number_to_string(x):
    """String(x) for a JavaScript number."""
    if isinstance(x, bool):
        return 'true' if x else 'false'
    x = float(x)
    if math.isnan(x):
        return 'NaN'
    if math.isinf(x):
        return 'Infinity' if x > 0 else '-Infinity'
    if x == 0:
        return '0'
    sign = '-' if x < 0 else ''
    digits, n = _shortest_digits(x)
    k = len(digits)
    if k <= n <= 21:
        return sign + digits + '0' * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + '.' + digits[n:]
    if -6 < n <= 0:
        return sign + '0.' + '0' * (-n) + digits
    e = n - 1
    mant = digits[0] + ('.' + digits[1:] if k > 1 else '')
    return sign + mant + 'e' + ('+' if e >= 0 else '-') + str(abs(e))


def js_to_precision(x, prec):
    """x.toPrecision(prec), then parseFloat — returns the rounded float.

    Ties round to the larger magnitude, exactly as JavaScript does.
    """
    if x == 0 or math.isnan(x) or math.isinf(x):
        return x
    d = Decimal(x)  # exact binary value
    adj = d.adjusted()
    q = Decimal(1).scaleb(adj - prec + 1)
    return float(d.quantize(q, rounding=ROUND_HALF_UP))


def js_to_exponential(x):
    """x.toExponential() with no argument (shortest digits)."""
    if math.isnan(x):
        return 'NaN'
    if math.isinf(x):
        return 'Infinity' if x > 0 else '-Infinity'
    if x == 0:
        return '0e+0'
    sign = '-' if x < 0 else ''
    digits, n = _shortest_digits(x)
    e = n - 1
    mant = digits[0] + ('.' + digits[1:] if len(digits) > 1 else '')
    return sign + mant + 'e' + ('+' if e >= 0 else '-') + str(abs(e))


def fmt_num(n):
    if not isinstance(n, (int, float)) or isinstance(n, bool) or (isinstance(n, float) and math.isnan(n)):
        return 'Not a number'
    n = float(n)
    if math.isinf(n):
        return '∞' if n > 0 else '-∞'
    if n == 0:
        return '0'
    a = abs(n)
    if a >= 1e15 or a < 1e-9:
        return js_to_exponential(js_to_precision(n, 10)).replace('e+', 'e')
    return js_number_to_string(js_to_precision(n, 12))


def parse_float(s):
    """JavaScript parseFloat: the longest numeric prefix, or NaN."""
    m = re.match(r'\s*([+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?))', str(s))
    if not m:
        return NAN
    t = m.group(1)
    if t.lstrip('+-') == 'Infinity':
        return -INF if t.startswith('-') else INF
    try:
        return float(t)
    except ValueError:
        return NAN
