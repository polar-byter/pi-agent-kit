"""Assemble the saved browser frames of the verified example."""
from pathlib import Path
import argparse
from PIL import Image


def build_game_recording(frames_directory, output_path):
    """Keep the recorded game area and preserve the order of its real states."""
    frames=[]
    for frame_index in range(7):
        frame_path=frames_directory / f'pi-game-{frame_index:02d}.png'
        with Image.open(frame_path) as screenshot:
            game_area=screenshot.crop((380,0,900,420)).convert('RGB')
            frames.append(game_area.convert('P',palette=Image.Palette.ADAPTIVE,colors=128))
    output_path.parent.mkdir(parents=True,exist_ok=True)
    frames[0].save(output_path,save_all=True,append_images=frames[1:],
                   duration=[1000,650,650,650,650,1800,1000],loop=0,disposal=2,optimize=True)
    return output_path


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames-directory',type=Path,default=Path(__file__).parent/'pi_game_frames')
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'pi_game_live.gif')
    options=parser.parse_args()
    print(build_game_recording(options.frames_directory,options.output))
