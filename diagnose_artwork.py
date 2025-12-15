from mutagen.flac import FLAC
from pathlib import Path

# Path to a failing file
file_path = Path("/home/daniel/build/python-audio-converter/in/Me Against the World/02 If I Die 2Nite.flac")

print(f"Loading file: {file_path}")
flac = FLAC(str(file_path))

if flac.pictures:
    print(f"Found {len(flac.pictures)} pictures")
    for i, pic in enumerate(flac.pictures):
        print(f"\nPicture {i}:")
        print(f"  Type: {type(pic)}")
        print(f"  Dir: {getattr(pic, 'desc', 'N/A')}")
        print(f"  Mime: {getattr(pic, 'mime', 'N/A')}")
        print(f"  Width: {getattr(pic, 'width', 'N/A')}")
        print(f"  Height: {getattr(pic, 'height', 'N/A')}")
        print(f"  Depth: {getattr(pic, 'depth', 'N/A')}")
        print(f"  Colors: {getattr(pic, 'colors', 'N/A')}")
        print(f"  Has .data: {'data' in dir(pic)}")
        print(f"  Data length: {len(getattr(pic, 'data', b'')) if 'data' in dir(pic) else 'No data attr'}")
        
        # Test _first_front_cover
        from pac.metadata import _first_front_cover
        front_cover = _first_front_cover(flac)
        print(f"\n_first_front_cover result: {type(front_cover)}")
        if front_cover is not None:
            print(f"  Length: {len(front_cover)}")
            print(f"  First 10 bytes: {front_cover[:10]}")
else:
    print("No pictures found")