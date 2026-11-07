import pytest
from pydantic import ValidationError

from app import schemas


@pytest.mark.parametrize("path", ["../x.mp4", "C:/x.mp4", "a/../../b.mp4", ""])
def test_file_camera_rejects_paths_outside_test_clips(path):
    with pytest.raises(ValidationError):
        schemas.CameraCreate(name="f", source_type="file", stream_path=path)


def test_file_camera_normalises_name():
    cam = schemas.CameraCreate(name="f", source_type="file", stream_path="\\sub\\clip.mp4")
    assert cam.stream_path == "sub/clip.mp4"


def test_site_update_validation():
    with pytest.raises(ValidationError):
        schemas.SiteUpdate(after_hours_from="24:00")
    with pytest.raises(ValidationError):
        schemas.SiteUpdate(timezone="Not/AZone")
    assert schemas.SiteUpdate(after_hours_from="20:00", timezone="Pacific/Auckland").after_hours_from == "20:00"
