import tempfile
import unittest
from pathlib import Path
from spatialforge.task_workspace import run_task_code


class TaskWorkspace(unittest.TestCase):
    def test_task_code_writes_outputs_but_cannot_modify_harness_assets_or_access_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);assets=root/'generated_assets';assets.mkdir();(assets/'source.txt').write_text('original')
            code='''from pathlib import Path
import socket
import json
from spatialforge.contracts import ASSETS
results={"catalog_imported":bool(ASSETS)}
Path("layout.json").write_text(json.dumps({"size":[4,5]}))
for key,path in [("harness","/harness/spatialforge/blocked_probe.txt"),("asset","/assets/source.txt")]:
    try:Path(path).write_text("bad")
    except OSError as exc:results[key]=exc.errno
    else:raise AssertionError("protected write succeeded")
results["secrets_visible"]=Path("/home/maqiang/GitHub/SpatialForge/service.local.json").exists()
try:socket.create_connection(("127.0.0.1",3841),timeout=.1)
except OSError:results["host_service_inaccessible"]=True
else:raise AssertionError("host service reachable")
print(json.dumps(results))
'''
            result=run_task_code(root,'test_scope',code,10)
            self.assertEqual(result['returncode'],0,result['stderr'])
            import json
            data=json.loads(result['stdout']);self.assertEqual(data['harness'],30);self.assertEqual(data['asset'],30)
            self.assertFalse(data['secrets_visible']);self.assertTrue(data['host_service_inaccessible'])
            self.assertTrue(data['catalog_imported']);self.assertEqual((assets/'source.txt').read_text(),'original')
            self.assertIn('layout.json',[r['file'] for r in result['artifacts']])
            with self.assertRaises(ValueError):run_task_code(root,'../outside','pass')

if __name__=='__main__':unittest.main()
