import numpy as np
import scipy as sp
import scipy.stats


def gaussian(x, mu, sig):
    return np.exp(-np.power(x - mu, 2.) / (2 * np.power(sig, 2.)))


def normal2D(x, y, sig):
    return np.exp(-(np.power(x, 2.) + np.power(y, 2.)) / (2 * np.power(sig, 2.)))


def normal_pdf_int_lookup(x, mean, std):
    max_amp = 2000
    norm_dist = sp.stats.norm.pdf(x=np.arange(-max_amp,max_amp), loc=0, scale=std)

    return norm_dist[x-mean+max_amp]


class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self


def apply_no_anim_boundary(x_bins, arm_coor, image):
    """
    
    Args:
        x_bins: the position value for each bin
        arm_coor: the inclusive arm coordinates of valid animal positions
        image: the image or array to apply

    Returns: 

    """
    # calculate no-animal boundary
    arm_coor = np.array(arm_coor, dtype='float64')
    arm_coor[:,0] -= x_bins[1] - x_bins[0]
    bounds = np.vstack([[x_bins[-1], 0], arm_coor])
    bounds = np.roll(bounds, -1)

    boundary_ind = np.searchsorted(x_bins, bounds, side='right')
    #boundary_ind[:,1] -= 1

    for bounds in boundary_ind:
        if image.ndim == 1:
            image[bounds[0]:bounds[1]] = 0
        elif image.ndim == 2:
            image[bounds[0]:bounds[1], :] = 0
            image[:, bounds[0]:bounds[1]] = 0
    return image


def simplify_pos_pandas(pos_data):
    pos_data_time = pos_data.loc[:, 'time']

    pos_data_notebook = pos_data.loc[:,'lin_dist_well']
    pos_data_notebook.loc[:, 'lin_vel_center'] = pos_data.loc[:,('lin_vel', 'well_center')]
    pos_data_notebook.loc[:, 'seg_idx'] = pos_data.loc[:,('seg_idx', 'seg_idx')]
    pos_data_notebook.loc[:,'timestamps'] = pos_data_time*30000
    pos_data_notebook = pos_data_notebook.set_index('timestamps')

    return pos_data_notebook


class Groupby:
    def __init__(self, data, keys):
        self.data = data
        _, self.keys_as_int = np.unique(keys, return_inverse=True)
        self.n_keys = max(self.keys_as_int)
        self.set_indices()

    def set_indices(self):
        self.indices = [[] for i in range(self.n_keys+1)]
        for i, k in enumerate(self.keys_as_int):
            self.indices[k].append(i)
        self.indices = [np.array(elt) for elt in self.indices]

    def apply(self, function, vector, broadcast):
        if broadcast:
            result = np.zeros(len(vector))
            for idx in self.indices:
                result[idx] = function(vector[idx])
        else:
            result = np.zeros(self.n_keys)
            for k, idx in enumerate(self.indices):
                result[self.keys_as_int[k]] = function(vector[idx])

        return result

    def __iter__(self):
        for inds in self.indices:
            yield self.data[inds]



