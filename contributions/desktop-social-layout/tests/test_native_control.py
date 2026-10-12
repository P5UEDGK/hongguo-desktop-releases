"""Exercise the actual patched validator without loading Win32/mpv resources."""
import ast
import math
from pathlib import Path
import sys

source = ast.parse(Path(sys.argv[1]).read_text(encoding='utf8'))
function = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == 'validate_control')
namespace = {'math': math}
exec(compile(ast.Module(body=[function], type_ignores=[]), '<native-validator>', 'exec'), namespace)
validate = namespace['validate_control']
for value in ([], [10, 20, 300, 200]):
    assert validate({'occlusion': value})['occlusion'] == value
for value in (None, {}, [1, 2], [1, 2, 3, 4, 5], [True, 2, 3, 4], [-1, 0, 1, 1], [0, 0, 32769, 1]):
    try:
        validate({'occlusion': value})
    except ValueError:
        pass
    else:
        raise AssertionError('Invalid occlusion accepted')
print('PASS: validated occlusion is retained by dict(body); malformed rectangles rejected')

# Execute the production empty-region branch with Win32 success/failure results.
from types import SimpleNamespace
branch=next(node for node in ast.walk(source) if isinstance(node,ast.If) and ast.unparse(node.test)=='not occlusion')
code=compile(ast.fix_missing_locations(ast.Module(body=[branch],type_ignores=[])),'<actual-region-clear>','exec')
for result in (0,1):
    try:exec(code,{'occlusion':[],'hwnd':1,'user':SimpleNamespace(SetWindowRgn=lambda *_:result)})
    except RuntimeError:
        assert result==0
    else:assert result==1,'failed native region clear must trigger recovery'
print('PASS: native empty-region failures trigger recovery')
