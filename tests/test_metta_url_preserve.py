import pytest
from biocypher_metta.metta_writer import MeTTaWriter


class DummyWriter(MeTTaWriter):
    def __init__(self):
        # Bypass BaseWriter heavy init by setting minimal attributes used by tests
        # We won't call super().__init__
        # Set attributes referenced by methods under test
        self.excluded_properties = []
        self.edge_node_types = {}
        self.label_is_ontology = {}
        self.type_hierarchy = {}
        self.output_path = "."
        self.bcy = None
        self.ontology = None


@pytest.fixture
def writer():
    return DummyWriter()


def test_preprocess_id_preserves_https_url(writer):
    url = "http://example.com/path:with:colons"
    out = writer.preprocess_id(url, preserve_prefix=False)
    assert "http://" in out or "https://" in out
    assert "://" in out


def test_normalize_text_preserves_urls(writer):
    label = "Some Label https://example.org/resource (extra)"
    out = writer.normalize_text(label)
    assert "https://example.org/resource" in out
    assert "some_label" in out  # other text normalized


def test_check_property_preserves_url(writer):
    prop = "https://example.com/some?query=1&x=2"
    out = writer.check_property(prop)
    assert out == prop.strip()


def test_check_property_sanitizes_other_text(writer):
    prop = "Some Value (weird) -> end"
    out = writer.check_property(prop)
    assert "Some_Value" in out 
    assert "->" not in out
    assert "weird" in out
