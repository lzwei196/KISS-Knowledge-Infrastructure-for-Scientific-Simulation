"""Explicit PCSE input formats; fixture parsing never launches a model."""
import datetime as dt
import hashlib
from pathlib import Path
import re

import pytest

from kiss_cli import flowgate

flowgate.load()
from ki_tools_common.flow import project_data_formats as formats

WEATHER = '''## Site Characteristics
Country = "China"; Station = "Wangjiaba_CMFD"; Description = "CMFD"
Source = "CMFD_3hr"; Contact = "hydrocraft"
Longitude = 115.6; Latitude = 32.43; Elevation = 28
AngstromA = 0.18; AngstromB = 0.55; HasSunshine = False
## Daily weather observations
DAY,IRRAD,TMIN,TMAX,VAP,WIND,RAIN,SNOWDEPTH
19800228,2538.000,-1.2,-0.7,0.539,2.9,5.15,0
19800229,1987.2,-1.2,0.4,0.586,1.2,0.43,NaN
19800301,2008.8,0.2,1.4,0.618,1.7,0.00,0
'''
AGRO = '''- 1980-06-01:
    CropCalendar:
        crop_name: maize
        variety_name: Grain_maize_201
        crop_start_date: 1980-06-15
        crop_start_type: sowing
        crop_end_date:
        crop_end_type: maturity
        max_duration: 200
    TimedEvents: null
    StateEvents: null
'''
WEATHER_CONTRACT = {"output_id": "weather", "path": "outputs/weather.csv",
                    "format": "pcse_weather_csv_v1", "date_format": "%Y%m%d"}
AGRO_CONTRACT = {"output_id": "agro", "path": "outputs/agro.yaml",
                 "format": "pcse_agromanagement_yaml_v1", "campaign_start": "1980-06-01"}


def test_public_contract_check_requires_no_file():
    assert formats.validate_contract(WEATHER_CONTRACT) is None
    assert formats.validate_contract(AGRO_CONTRACT) is None


@pytest.mark.parametrize("invalid", [None, [], {}, {"format": []}, {"format": {}},
                                     {**WEATHER_CONTRACT, "path": "outputs/../weather.csv"},
                                     {**WEATHER_CONTRACT, "date_format": "%Y-%m-%d"}])
def test_public_contract_check_rejects_malformed_types_as_value_error(invalid):
    with pytest.raises(ValueError):
        formats.validate_contract(invalid)


def validate(tmp_path, text, contract=WEATHER_CONTRACT):
    path = tmp_path / contract["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    before = path.read_bytes()
    report = formats.validate_output(path, contract)
    assert path.read_bytes() == before
    assert report["scientific_validation"] == "not_performed"
    assert report["model_ready"] is False
    return report


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_valid_weather_preserves_raw_identity_and_complete_leap_dates(tmp_path, newline):
    body = WEATHER.replace("\n", newline)
    report = validate(tmp_path, body)
    assert report["ok"], report
    assert report["sha256"] == hashlib.sha256(body.encode()).hexdigest()
    assert report["path"] == "outputs/weather.csv"
    assert report["policy_sha256"] == formats.source_digest()
    assert report["facts"]["row_count"] == 3
    assert report["facts"]["first_date"] == "1980-02-28"
    assert report["facts"]["last_date"] == "1980-03-01"
    assert report["facts"]["snowdepth_missing_count"] == 1
    assert report["facts"]["implicit_selection"] is False


@pytest.mark.parametrize("old,new", [
    ('Country = "China";', ''),
    ('Country = "China";', 'Country = "China"; Country = "China";'),
    ('Country = "China";', 'Unknown = "China";'),
    ('Country = "China";', 'Country = str("China");'),
    ('Country = "China";', 'Country = __import__("os").getcwd();'),
    ('Country = "China";', 'Country = ["China"];'),
    ('Country = "China";', 'Country = "China=CN";'),
    ('Latitude = 32.43', 'Latitude = 100'),
    ('Latitude = 32.43', 'Latitude = True'),
    ('Elevation = 28', 'Elevation = 1e999'),
    ('HasSunshine = False', 'HasSunshine = "False"'),
    ('HasSunshine = False', 'HasSunshine = True'),
    ('AngstromA = 0.18', 'AngstromA = 0.01'),
    ('DAY,IRRAD,TMIN,TMAX,VAP,WIND,RAIN,SNOWDEPTH', 'DAY,IRRAD,TMIN,TMAX,VAP,WIND,RAIN,RAIN'),
    ('DAY,IRRAD,TMIN,TMAX,VAP,WIND,RAIN,SNOWDEPTH', 'DAY,IRRAD,TMIN,TMAX,VAP,WIND,RAIN'),
    ('19800229', '19800228'),
    ('19800229', '19800301'),
    ('19800229', '19810229'),
    ('19800229', '1980-02-29'),
    ('2538.000', 'NaN'),
    ('2538.000', 'inf'),
    ('2538.000', '-1'),
    ('-1.2,-0.7', '2.0,1.0'),
    ('2.9,5.15,0', '2.9,-5.15,0'),
    ('2.9,5.15,0', '2.9,5.15,inf'),
    ('2.9,5.15,0', '2.9,5.15,'),
    ('2.9,5.15,0', '2.9,5.15'),
    ('## Daily weather observations', '## Not a recognized marker'),
])
def test_invalid_weather_fails_typed_validation(tmp_path, old, new):
    assert old in WEATHER
    assert validate(tmp_path, WEATHER.replace(old, new, 1))["ok"] is False


def test_no_implicit_metadata_skipping_or_empty_weather(tmp_path):
    assert not validate(tmp_path / "bare", WEATHER[WEATHER.index("DAY,"):])["ok"]
    assert not validate(tmp_path / "empty", WEATHER[:WEATHER.index("19800228")])["ok"]
    # The broken DS adapter retained comment lines and lost all site metadata.
    broken = "\n".join(line for line in WEATHER.splitlines() if "=" not in line) + "\n"
    assert not validate(tmp_path / "lost-metadata", broken)["ok"]


def test_bounds_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(formats, "MAX_WEATHER_BYTES", 32)
    assert not validate(tmp_path / "bytes", WEATHER)["ok"]
    monkeypatch.setattr(formats, "MAX_WEATHER_BYTES", 32 * 1024 * 1024)
    monkeypatch.setattr(formats, "MAX_WEATHER_ROWS", 2)
    assert not validate(tmp_path / "rows", WEATHER)["ok"]
    monkeypatch.setattr(formats, "MAX_WEATHER_ROWS", 200000)
    monkeypatch.setattr(formats, "MAX_METADATA_LINES", 3)
    assert not validate(tmp_path / "metadata", WEATHER)["ok"]


def test_single_native_date_campaign_acceptance(tmp_path):
    report = validate(tmp_path, AGRO, AGRO_CONTRACT)
    assert report["ok"], report
    assert report["facts"] == {"campaign_count": 1, "campaign_start": "1980-06-01",
        "crop_name": "maize", "variety_name": "Grain_maize_201", "crop_start_date": "1980-06-15",
        "crop_end_type": "maturity", "crop_end_date": None, "max_duration": 200,
        "duration_limit_date": "1981-01-01", "events_present": False, "implicit_selection": False}


@pytest.mark.parametrize("old,new", [
    ('- 1980-06-01:', '- 1981-06-01:'),
    ('- 1980-06-01:', '- "1980-06-01":'),
    ('crop_start_date: 1980-06-15', 'crop_start_date: "1980-06-15"'),
    ('crop_start_date: 1980-06-15', 'crop_start_date: 1980-05-15'),
    ('crop_start_type: sowing', 'crop_start_type: guessed'),
    ('crop_end_type: maturity', 'crop_end_type: guessed'),
    ('crop_end_type: maturity', 'crop_end_type: harvest'),
    ('crop_end_date:', 'crop_end_date: 1980-06-01'),
    ('max_duration: 200', 'max_duration: 0'),
    ('max_duration: 200', 'max_duration: true'),
    ('max_duration: 200', 'max_duration: .nan'),
    ('max_duration: 200', 'max_duration: .inf'),
    ('max_duration: 200', 'max_duration: 200\n        max_duration: 300'),
    ('crop_name: maize', 'crop_name: maize\n        crop_name: wheat'),
    ('crop_name: maize', 'crop_name: !!python/object/apply:os.system [echo unsafe]'),
    ('crop_name: maize', 'crop_name: &crop maize'),
    ('crop_name: maize', 'crop_name: *crop'),
    ('TimedEvents: null', 'TimedEvents: []'),
    ('StateEvents: null', 'StateEvents: []'),
    ('StateEvents: null', 'StateEvents: null\n    Unknown: null'),
])
def test_ambiguous_unsafe_or_wrong_campaign_yaml_is_rejected(tmp_path, old, new):
    assert validate(tmp_path, AGRO.replace(old, new, 1), AGRO_CONTRACT)["ok"] is False


def test_yaml_multiple_documents_campaigns_and_parser_limits(tmp_path, monkeypatch):
    for index, body in enumerate([AGRO + "---\n" + AGRO, AGRO + AGRO.replace("1980", "1981"), "[]", "null", "x: y"]):
        assert not validate(tmp_path / str(index), body, AGRO_CONTRACT)["ok"]
    monkeypatch.setattr(formats, "MAX_YAML_EVENTS", 8)
    assert not validate(tmp_path / "events", AGRO, AGRO_CONTRACT)["ok"]
    monkeypatch.setattr(formats, "MAX_YAML_EVENTS", 4096)
    monkeypatch.setattr(formats, "MAX_YAML_DEPTH", 2)
    assert not validate(tmp_path / "depth", AGRO, AGRO_CONTRACT)["ok"]


@pytest.mark.parametrize("key,value", [("format", "generic_yaml"), ("date_format", "%Y-%m-%d"),
    ("extra", "ignored?"), ("output_id", ""), ("path", "../outside.csv"),
    ("path", "outputs/../outside.csv"), ("path", "outputs//weather.csv"),
    ("path", "outputs\\weather.csv"), ("path", "outputs/${RUN}.csv"), ("path", "outputs/weather.txt")])
def test_unknown_or_ambiguous_contract_is_never_inferred(tmp_path, key, value):
    path = tmp_path / "weather.csv"
    path.write_text(WEATHER, encoding="utf-8")
    contract = {**WEATHER_CONTRACT, key: value}
    assert formats.validate_output(path, contract)["ok"] is False


def test_real_case_faithful_date_only_and_first_campaign_bytes(tmp_path):
    case = Path(__file__).resolve().parents[2] / "models/WOFOST/outputs/wangjiaba"
    weather_source = case / "weather_wangjiaba.csv"
    agro_source = case / "agro_maize.yaml"
    weather_raw, agro_raw = weather_source.read_bytes(), agro_source.read_bytes()
    lines = weather_raw.splitlines(keepends=True)
    header = next(i for i, line in enumerate(lines) if line.startswith(b"DAY,"))
    converted = lines[:header + 1]
    for line in lines[header + 1:]:
        date, comma, rest = line.partition(b",")
        assert comma and dt.date.fromisoformat(date.decode("ascii"))
        converted.append(date.replace(b"-", b"") + comma + rest)
    weather_output = b"".join(converted)
    # Every preamble/header byte and every non-DAY byte, including newline and
    # numeric spelling/precision, remains identical. No implicit year clipping.
    assert converted[:header + 1] == lines[:header + 1]
    assert [line.partition(b",")[2] for line in converted[header + 1:]] == [line.partition(b",")[2] for line in lines[header + 1:]]
    weather_report = validate(tmp_path, weather_output)
    assert weather_report["ok"], weather_report
    assert weather_report["facts"]["row_count"] == 4018
    assert weather_report["facts"]["first_date"] == "1980-01-01"
    assert weather_report["facts"]["last_date"] == "1990-12-31"
    campaign_starts = list(re.finditer(rb"(?m)^- [0-9]{4}-[0-9]{2}-[0-9]{2}:", agro_raw))
    assert len(campaign_starts) == 11 and campaign_starts[0].start() == 0
    first_campaign = agro_raw[:campaign_starts[1].start()]
    assert first_campaign.startswith(b"- 1980-06-01:")
    agro_report = validate(tmp_path, first_campaign, AGRO_CONTRACT)
    assert agro_report["ok"], agro_report
    assert (tmp_path / AGRO_CONTRACT["path"]).read_bytes() == first_campaign
    assert weather_source.read_bytes() == weather_raw and agro_source.read_bytes() == agro_raw
