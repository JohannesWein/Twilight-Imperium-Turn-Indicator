import ujson
def t(label,v):
    try:
        print(label, ujson.loads(v))
    except Exception as e:
        print(label, 'EXC', type(e).__name__, e)
t('1)', '{"x":1}')
t('2)', b'{"x":1}')
