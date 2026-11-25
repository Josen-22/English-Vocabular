"""Convert the approved raster master to Windows icon resources (build time only)."""
from pathlib import Path
import argparse

from PIL import Image


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('master',type=Path)
    args=parser.parse_args()
    assets=Path(__file__).resolve().parents[1]/'src'/'assets'
    assets.mkdir(parents=True,exist_ok=True)
    with Image.open(args.master) as original:
        image=original.convert('RGBA')
        if image.width!=image.height or image.getextrema()[3][0]!=0:
            raise ValueError('The approved master must be square with genuine transparency.')
        image.resize((256,256),Image.Resampling.LANCZOS).save(assets/'vocab-icon.png')
        image.save(assets/'vocab-icon.ico',format='ICO',sizes=[(n,n) for n in (16,20,24,32,40,48,64,128,256)])
    print('Generated vocab-icon.png and nine-size vocab-icon.ico')


if __name__=='__main__':
    main()
