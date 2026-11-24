"""Local launcher and compatibility factory. Containers use their own entrypoints."""
import os

def create_app(config=None):
    service = (config or {}).get('SERVICE', os.getenv('SERVICE', 'catalog'))
    if service == 'catalog':
        from .catalog import create_app as factory
    elif service == 'reservation':
        from .reservation import create_app as factory
    else:
        raise RuntimeError('Unknown SERVICE')
    return factory(config)

if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=int(os.getenv('PORT', '8001')), debug=False)
