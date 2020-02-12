from matplotlib import cm
from matplotlib import colors
from PIL import Image
import numpy as np
import h5py
import sys

h5 = h5py.File(sys.argv[1])
print(h5.attrs['cluttercount'])
print(h5.attrs['range'])

for i in range(0,150,10):
    print(i)

    # Thresholded images for the radars
    binary = {}
    for radar in ['NL60', 'NL61']:
        binary[radar] = np.greater(h5[radar],i)
    binary['overlap'] = np.product(binary.values(), 0)
    for k, v in binary.items():
        Image.fromarray(
            cm.gray(
                colors.Normalize()(v),
                bytes=True,
            ),
        ).save('threshold_{:03.0f}_{}.png'.format(float(i), k))
    rgba = np.zeros(binary['overlap'].shape + (4,), dtype=np.uint8)
    mask = ~np.bool8(binary['overlap'])
    rgba[..., 0] = binary['NL60'] * mask
    rgba[..., 1] = 0
    rgba[..., 2] = binary['NL61'] * mask
    rgba[..., 3] = np.logical_or(binary['NL60'], binary['NL61'])
    Image.fromarray(
        rgba * 255,
    ).save('threshold_{:03.0f}_{}.png'.format(float(i), 'color'))

