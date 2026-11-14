"""Synthetic presenter geometry tests; no personal artwork/render/generation/network."""
import importlib.util
import json
import tempfile
import struct
from pathlib import Path
import sys
import unittest
SCRIPTS=Path(__file__).resolve().parent
sys.path.insert(0,str(SCRIPTS))
from prepare_job import validate_presenter,ROOT
SOURCES={}

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=tempfile.TemporaryDirectory()
        p=Path(cls.fixture.name)/'synthetic-header.png'
        p.write_bytes(b'\x89PNG\r\n\x1a\n'+b'\0\0\0\rIHDR'+struct.pack('>II',400,400))
        for name in ['pose_stand','pose_present','pose_point','pose_explain','pose_greeting_bow']:
            SOURCES[name]={'path':str(p)}
    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def test_default_all_poses(self):
        for pose in SOURCES:validate_presenter({'pose':pose},SOURCES)
    def test_small_support(self):
        validate_presenter({'pose':'pose_point','presenter':{'x':28,'y':1570,'width':225}},SOURCES)
    def test_large_host_reserved_upper_region(self):
        for pose in SOURCES:validate_presenter({'pose':pose,'presenter':{'x':40,'y':650,'width':540}},SOURCES)
    def test_hidden(self):
        validate_presenter({'pose':'pose_point','hidePresenter':True},SOURCES)
    def test_invalid_numeric(self):
        for value in [float('nan'),float('inf'),True,-1,0]:
            with self.assertRaises(ValueError):validate_presenter({'presenter':{'width':value}},SOURCES)
    def test_outside_canvas(self):
        for box in [{'x':1000,'width':500},{'y':1800,'width':500},{'x':-1}]:
            with self.assertRaises(ValueError):validate_presenter({'presenter':box},SOURCES)
    def test_bad_schema(self):
        for layout in [None,[],{'size':400}]:
            with self.assertRaises(ValueError):validate_presenter({'presenter':layout},SOURCES)
    def test_hidden_must_be_boolean(self):
        with self.assertRaises(ValueError):validate_presenter({'hidePresenter':'yes'},SOURCES)

if __name__=='__main__':unittest.main()
