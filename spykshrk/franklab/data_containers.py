import numpy as np
import pandas as pd
import functools
from abc import ABC, ABCMeta, abstractclassmethod, abstractmethod
from itertools import product
import uuid
import enum
import os

from spykshrk.franklab.pp_decoder.util import gaussian
from spykshrk.util import AttrDict, EnumMapping


class UnitTime(EnumMapping):
    SEC = 1
    SECOND = 1
    SAMPLE = 2
    MS = 3
    MILLISECOND = 3


def partialclass(cls, *args, **kwds):

    NewCls = type('_' + cls.__name__, (cls,),
                  {'__init__': functools.partialmethod(cls.__init__, *args, **kwds),
                   '__module__': __name__})

    return NewCls


class DataFormatError(RuntimeError):
    pass


def pos_col_format(ind, num_bins):
    return 'x{:0{dig}d}'.format(ind, dig=len(str(num_bins)))


class SeriesClass(pd.Series):
    _metadata = pd.Series._metadata + ['history', 'kwds']

    def __init__(self, data=None, index=None, dtype=None, name=None,
                 copy=False, fastpath=False, history=None, **kwds):
        super().__init__(data=data, index=index, dtype=dtype, name=name, copy=copy, fastpath=fastpath)
        self.history = history
        self.kwds = kwds

    @property
    def _constructor(self):
        return partialclass(type(self), history=self.history, **self.kwds)

    @property
    def _constructor_expanddim(self):
        # TODO: DataFrameClass is abstract, shouldn't be created
        return partialclass(DataFrameClass, history=self.history, **self.kwds)


class DataFrameClass(pd.DataFrame):

    _metadata = pd.DataFrame._metadata + ['kwds', 'history']
    _internal_names = pd.DataFrame._internal_names + ['uuid']
    _internal_names_set = set(_internal_names)

    def __init__(self, data=None, index=None, columns=None, dtype=None, copy=False, parent=None, history=None, **kwds):
        """
        
        Args:
            data: 
            index: 
            columns: 
            dtype: 
            copy: 
            parent: Uses parent history if avaliable.
            history: List that is set as the history of this object.  
                Overrides both the history of the parent and data source.
            **kwds: 
        """
        # print('called for {} with shape {}'.format(type(data), data.shape))
        self.uuid = uuid.uuid4()
        self.kwds = kwds

        if history is not None:
            self.history = list(history)
        elif parent is not None:
            if hasattr(parent, 'history'):
                self.history = list(parent.history)
                self.history.append(parent)
            else:
                self.history = [parent]
        else:
            if hasattr(data, 'history'):
                self.history = list(data.history)
                self.history.append(data)
            else:
                self.history = [data]
        #self.history.append(self)

        super().__init__(data, index, columns, dtype, copy)

    def __setstate__(self, state):
        # Insert new uuid (internal value)
        self.uuid = uuid.uuid4()
        super().__setstate__(state)

    #def __setstate__(self, state):
    #    #self.__init__(data=state['_data'], history=state['history'], kwds=state['kwds'])
    #    self.__dict__.update(state.copy())

    # def __getstate__(self):
    #     state = self.__dict__.copy()
    #     return state

    @property
    def _constructor(self):
        if hasattr(self, 'history'):
            return partialclass(type(self), history=self.history, **self.kwds)
        else:
            return type(self, **self.kwds)

    @property
    def _constructor_sliced(self):
        return SeriesClass

    @property
    def _constructor_expanddim(self):
        raise NotImplementedError

    @classmethod
    @abstractclassmethod
    def create_default(cls, df, parent=None, **kwd):
        pass

    def to_dataframe(self):
        return pd.DataFrame(self)

    def _to_hdf_store(self, direc, filename, hdf_base, hdf_grps, hdf_label):
        with pd.HDFStore(os.path.join(direc, filename), 'w') as store:
            main_path = os.path.join(hdf_base, hdf_grps, hdf_label)
            store[main_path] = self.to_dataframe()
            save_history = []
            for hist_en in self.history:
                try:
                    save_history.append((type(hist_en), hist_en.uuid))
                except AttributeError:
                    save_history.append((type(hist_en), repr(hist_en)))

            main_storer = store.get_storer(main_path)
            main_storer.attrs.history = save_history
            main_storer.attrs.kwds = self.kwds
            main_storer.attrs.classtype = type(self)

    @classmethod
    def _from_hdf_store(cls, direc, filename, hdf_base, hdf_grps, hdf_label):
        with pd.HDFStore(os.path.join(direc, filename), 'r') as store:
            main_path = os.path.join(hdf_base, hdf_grps, hdf_label)
            dataframe = store[main_path]
            main_storer = store.get_storer(main_path)
            save_history = main_storer.attrs.history
            kwds = main_storer.attrs.kwds
            newcls = main_storer.attrs.classtype

            return newcls(data=dataframe, history=save_history, kwds=kwds)

    def __repr__(self):
        return '<{}: {}, shape: ({})>'.format(self.__class__.__name__, self.uuid, self.shape)


class DayEpochEvent(DataFrameClass):
    _metadata = DataFrameClass._metadata + ['time_unit']

    def __init__(self, **kwds):
        self.time_unit = kwds['time_unit']  # type: UnitTime
        data = kwds['data']
        index = kwds['index']

        if isinstance(data, pd.DataFrame):
            if not isinstance(data.index, pd.MultiIndex):
                raise DataFormatError("DataFrame index must use MultiIndex as index.")

            if not all([col in data.index.names for col in ['day', 'epoch', 'event']]):
                raise DataFormatError("DayEpochTimeSeries must have index with 3 levels named: "
                                      "day, epoch, event.")

            if not all([col in data.columns for col in ['starttime', 'endtime']]):
                raise DataFormatError("RippleTimes must contain columns 'starttime' and 'endtime'.")

        if index is not None and not isinstance(index, pd.MultiIndex):
            raise DataFormatError("Index to be set must be MultiIndex.")

        super().__init__(**kwds)

    def get_range_view(self):
        return self[['starttime', 'endtime']]

    def get_num_events(self):
        return len(self)

    def find_events(self, times):
        event_id_list = []
        for time in times:
            res = self.query('starttime < @time and endtime > @time')
            id_list = res.index.get_level_values('event')
            event_id_list.extend(id_list)

        return event_id_list


class DayEpochTimeSeries(DataFrameClass):

    _metadata = DataFrameClass._metadata + ['sampling_rate']

    def __init__(self, **kwds):
        self.sampling_rate = kwds['sampling_rate']
        data = kwds['data']
        index = kwds['index']

        if isinstance(data, pd.DataFrame):
            if not isinstance(data.index, pd.MultiIndex):
                raise DataFormatError("DataFrame index must use MultiIndex as index.")

            if not all([col in data.index.names for col in ['day', 'epoch', 'timestamp', 'time']]):
                raise DataFormatError("DayEpochTimeSeries must have index with 4 levels named: "
                                      "day, epoch, timestamp, time.")

            epoch_grps = data.groupby(['day', 'epoch'])
            try:
                kwds['kwds']['start_times'] = []
                kwds['kwds']['start_timestamps'] = []
            except KeyError:
                kwds['kwds'] = {}
                kwds['kwds']['start_times'] = []
                kwds['kwds']['start_timestamps'] = []

            for key, epoch_data in epoch_grps:
                kwds['kwds']['start_times'].append(epoch_data.index.get_level_values('time')[0])
                kwds['kwds']['start_timestamps'].append(epoch_data.index.get_level_values('timestamp')[0])

        if index is not None and not isinstance(index, pd.MultiIndex):
            raise DataFormatError("Index to be set must be MultiIndex.")

        super().__init__(**kwds)

    @classmethod
    @abstractclassmethod
    def create_default(cls, df, sampling_rate, parent=None, **kwds):
        pass

    def get_time(self):
        return self.index.get_level_values('time')

    def get_timestamp(self):
        return self.index.get_level_values('timestamp')

    def get_time_range(self):
        return [self.index.get_level_values('time')[0], self.index.get_level_values('time')[-1]]

    def get_time_start(self):
        return self.index.get_level_values('time')[0]

    def get_time_end(self):
        return self.index.get_level_values('time')[-1]

    def get_time_total(self):
        return self.get_time_end() - self.get_time_start()

    def get_relative_index(self, inplace=False):
        if inplace:
            ret_data = self
            ind = self.index
        else:
            ret_data = self.copy()
            ind = ret_data.index
        ind.set_levels(level='time', levels=(self.index.get_level_values('time') -
                                             self.index.get_level_values('time')[0]), inplace=True)
        ind.set_levels(level='timestamp', levels=(self.index.get_level_values('timestamp') -
                                                  self.index.get_level_values('timestamp')[0]), inplace=True)

        return ret_data

    def get_resampled(self, bin_size):
        """
        
        Args:
            bin_size: size of time 
7
        Returns (LinearPositionContainer): copy of self with times resampled using backfill.

        """

        def epoch_rebin_func(df):
            day = df.index.get_level_values('day')[0]
            epoch = df.index.get_level_values('epoch')[0]

            new_timestamps = np.arange(df.index.get_level_values('timestamp')[0] +
                                       (bin_size - df.index.get_level_values('timestamp')[0] % bin_size),
                                       df.index.get_level_values('timestamp')[-1]+1, bin_size)
            new_times = new_timestamps / float(self.sampling_rate)

            new_indices = pd.MultiIndex.from_tuples(list(zip(
                new_timestamps, new_times)), names=['timestamp', 'time'])

            #df.set_index(df.index.get_level_values('timestamp'), inplace=True)
            pos_data_bin_ids = np.arange(0, len(new_timestamps), 1)

            pos_data_binned = df.loc[day, epoch].reindex(new_indices, method='ffill')
            #pos_data_binned.set_index(new_timestamps)
            pos_data_binned['bin'] = pos_data_bin_ids

            return pos_data_binned

        grp = self.groupby(level=['day', 'epoch'])

        pos_data_rebinned = grp.apply(epoch_rebin_func)
        return type(self)(pos_data_rebinned, history=self.history, **self.kwds)

    def get_irregular_resampled(self, timestamps):

        grp = self.groupby(level=['day', 'epoch'])
        for (day, epoch), grp_df in grp:
            ind = pd.MultiIndex.from_arrays([[day]*len(timestamps), [epoch]*len(timestamps),
                                             timestamps, np.array(timestamps)/
                                             float(self.sampling_rate)],
                                            names=['day', 'epoch', 'timestamp', 'time'])

            return grp_df.reindex(ind, method='ffill', fill_value=0)

    def apply_time_event(self, time_ranges: DayEpochEvent, event_mask_name='event_grp'):
        grouping = np.full(len(self), -1)
        time_index = self.index.get_level_values('time')
        for event_id, (range_start, range_end) in zip(time_ranges.index.get_level_values('event'),
                                                       time_ranges.get_range_view().values):
            range_mask = (time_index > range_start) & (time_index < range_end)
            grouping[range_mask] = event_id

        self[event_mask_name] = grouping

        return self


class DayEpochElecTimeChannelSeries(DayEpochTimeSeries):

    _metadata = DayEpochTimeSeries._metadata

    def __init__(self, sampling_rate, **kwds):
        data = kwds['data']
        index = kwds['index']

        if isinstance(data, pd.DataFrame):
            if not isinstance(data.index, pd.MultiIndex):
                raise DataFormatError("DataFrame index must use MultiIndex as index.")

            if not all([col in data.index.names for col in ['day', 'epoch', 'elec_grp_id',
                                                            'timestamp', 'time', 'channel']]):
                raise DataFormatError("DayEpochTimeSeries must have index with 6 levels named: "
                                      "day, epoch, elec_grp_id, timestamp, time.")

        if index is not None and not isinstance(index, pd.MultiIndex):
            raise DataFormatError("Index to be set must be MultiIndex.")

        super().__init__(sampling_rate=sampling_rate, **kwds)


class DayEpochElecTimeSeries(DayEpochTimeSeries):

    _metadata = DayEpochTimeSeries._metadata

    def __init__(self, sampling_rate, **kwds):
        data = kwds['data']
        index = kwds['index']

        if isinstance(data, pd.DataFrame):
            if not isinstance(data.index, pd.MultiIndex):
                raise DataFormatError("DataFrame index must use MultiIndex as index.")

            if not all([col in data.index.names for col in ['day', 'epoch', 'elec_grp_id', 'timestamp', 'time']]):
                raise DataFormatError("DayEpochTimeSeries must have index with 6 levels named: "
                                      "day, epoch, elec_grp_id, timestamp, time.")

        if index is not None and not isinstance(index, pd.MultiIndex):
            raise DataFormatError("Index to be set must be MultiIndex.")

        super().__init__(sampling_rate=sampling_rate, **kwds)


class EncodeSettings:
    """
    Mapping of encoding parameters from realtime configuration into class attributes for easy access.
    """
    def __init__(self, realtime_config):
        """
        
        Args:
            realtime_config (dict[str, *]): JSON realtime configuration imported as a dict
        """
        encoder_config = realtime_config['encoder']

        self.sampling_rate = encoder_config['sampling_rate']
        self.arm_coordinates = encoder_config['position']['arm_pos']

        self.pos_upper = encoder_config['position']['upper']
        self.pos_lower = encoder_config['position']['lower']
        self.pos_num_bins = encoder_config['position']['bins']
        self.pos_bin_delta = ((self.pos_upper - self.pos_lower) / self.pos_num_bins)
        self.pos_col_names = [pos_col_format(ii, self.pos_num_bins) for ii in range(self.pos_num_bins)]

        self.pos_bins = np.linspace(0, self.pos_bin_delta * (self.pos_num_bins - 1), self.pos_num_bins)
        self.pos_bin_edges = np.linspace(0, self.pos_bin_delta * self.pos_num_bins, self.pos_num_bins+1)

        self.pos_kernel_std = encoder_config['position_kernel']['std']

        self.pos_kernel = gaussian(self.pos_bins,
                                   self.pos_bins[int(len(self.pos_bins)/2)],
                                   self.pos_kernel_std)

        self.mark_kernel_mean = encoder_config['mark_kernel']['mean']
        self.mark_kernel_std = encoder_config['mark_kernel']['std']

    def pos_column_name(self, pos_ind):
        return pos_col_format(pos_ind, self.pos_num_bins)

    @property
    def pos_column_slice(self):
        return slice(self.pos_col_names[0], self.pos_col_names[-1])

    @pos_column_slice.setter
    def pos_column_slice(self, slice):
        raise NotImplementedError


class DecodeSettings:
    """
    Mapping of decoding parameters from realtime configuration into class attributes for easy access.
    """
    def __init__(self, realtime_config):
        """
        
        Args:
            realtime_config (dict[str, *]): JSON realtime configuration imported as a dict
        """
        self.time_bin_size = realtime_config['pp_decoder']['bin_size']     # Decode bin size in samples (usually 30kHz)
        self.trans_smooth_std = realtime_config['pp_decoder']['trans_mat_smoother_std']
        self.trans_uniform_gain = realtime_config['pp_decoder']['trans_mat_uniform_gain']


class SpikeWaves(DayEpochElecTimeChannelSeries):

    _metadata = DayEpochElecTimeChannelSeries._metadata

    def __init__(self, data=None, index=None, columns=None, dtype=None,
                 copy=False, parent=None, history=None, sampling_rate=0, **kwds):

        super().__init__(sampling_rate=sampling_rate, data=data, index=index, columns=columns,
                         dtype=dtype, copy=copy, parent=parent,
                         history=history, **kwds)

    @classmethod
    def create_default(cls, df, sampling_rate, parent=None, **kwds):
        if parent is None:
            parent = df

        return cls(sampling_rate=sampling_rate, df=df, parent=parent, **kwds)

    @classmethod
    def from_df(cls, df, enc_settings, parent=None, **kwds):
        df['time'] = df.index.get_level_values('timestamp') / float(enc_settings.sampling_rate)
        df.set_index('time', append=True, inplace=True)
        #df.index = df.index.swaplevel(4, 5)
        return cls(sampling_rate=enc_settings.sampling_rate, data=df, enc_settings=enc_settings,
                   parent=parent, **kwds)


class SpikeFeatures(DayEpochElecTimeSeries):

    _metadata = DayEpochElecTimeSeries._metadata

    def __init__(self, data=None, index=None, columns=None, dtype=None,
                 copy=False, parent=None, history=None, sampling_rate=0, **kwds):
        super().__init__(sampling_rate=sampling_rate, data=data, index=index, columns=columns,
                         dtype=dtype, copy=copy, parent=parent, history=history, **kwds)

    @classmethod
    def create_default(cls, df, sampling_rate, parent=None, **kwds):
        if parent is None:
            parent = df

        return cls(sampling_rate=sampling_rate, data=df, parent=parent, **kwds)

    @classmethod
    def from_numpy_single_epoch_elec(cls, day, epoch, elec_grp, timestamp, amps, sampling_rate):
        ind = pd.MultiIndex.from_arrays([[day]*len(timestamp), [epoch]*len(timestamp), [elec_grp]*len(timestamp),
                                         timestamp, timestamp/float(sampling_rate)],
                                        names=['day', 'epoch', 'elec_grp_id', 'timestamp', 'time'])

        return cls(sampling_rate=sampling_rate, data=amps, index=ind)

    def get_above_threshold(self, threshold):
        ind = np.nonzero(np.any(self.values > threshold, axis=1))
        return self.iloc[ind]

    def get_simple_index(self):
        """
        Only use if MultiIndex has been selected for day, epoch, and tetrode.
        Returns:

        """

        return self.set_index(self.index.get_level_values('timestamp'))


class LinearPosition(DayEpochTimeSeries):
    """
    Container for Linearized position read from an AnimalInfo.  
    
    The linearized position can come from Frank Lab's Matlab data read by the NSpike data parser
    (spykshrk.realtime.simulator.nspike_data), using the AnimalInfo class to parse the directory
    structure and PosMatDataStream to parse the linearized position files.
    """

    _metadata = DayEpochTimeSeries._metadata + ['arm_coord']

    def __init__(self, data=None, index=None, columns=None, dtype=None,
                 copy=False, parent=None, history=None, sampling_rate=0, **kwds):
        super().__init__(sampling_rate=sampling_rate, data=data, index=index, columns=columns,
                         dtype=dtype, copy=copy, parent=parent, history=history, **kwds)

        try:
            self.arm_coord = kwds['arm_coord']
        except KeyError:
            # Likely called with a blockmanager called, which shouldn't propagate
            self.arm_coord = None

    @classmethod
    def create_default(cls, df, sampling_rate, arm_coord, parent=None, **kwds):
        if parent is None:
            parent = df

        return cls(df=df, sampling_rate=sampling_rate, arm_coord=arm_coord, parent=parent, **kwds)

    @classmethod
    def from_nspike_posmat(cls, nspike_pos_data, enc_settings: EncodeSettings, parent=None):
        """
        
        Args:
            parent: 
            nspike_pos_data: The position panda table from an animal info.  Expects a specific multi-index format.
            enc_settings: Encoder settings, used to get the endpoints of the W track
        """
        if parent is None:
            parent = nspike_pos_data

        return cls(sampling_rate=enc_settings.sampling_rate, arm_coord=enc_settings.arm_coordinates,
                   data=nspike_pos_data, parent=parent, enc_settings=enc_settings)

        # make sure there's a time field

    # @property
    # def _constructor(self):
    #     #construct_func = super()._constructor(self)
    #     print(type(self), self.arm_coord)
    #     return functools.partial(type(self), history=self.history, **self.kwds)

        #return functools.partial(construct_func, arm_coord=self.arm_coord)

    def get_pd_no_multiindex(self):
        """
        Removes the MultiIndexes, for a simplier panda table. Maintains well distances, 
        reduces velocity to just center velocity, and removes day and epoch info from index.
        
        This should not be used for multi-day datasets where the timestamp resets.
        
        Returns: Copy of linearized panda table with MultiIndexes removed

        """

        pos_data_time = self.index.get_level_values('time')
        pos_data_timestamp = self.index.get_level_values('timestamp')

        pos_data_simple = self.loc[:, 'lin_dist_well'].copy()
        pos_data_simple.loc[:, 'lin_vel_center'] = self.loc[:, ('lin_vel', 'well_center')]
        pos_data_simple.loc[:, 'seg_idx'] = self.loc[:, ('seg_idx', 'seg_idx')]
        pos_data_simple.loc[:, 'time'] = pos_data_time
        pos_data_simple.loc[:, 'timestamp'] = pos_data_timestamp
        pos_data_simple = pos_data_simple.set_index('timestamp')

        return pos_data_simple

    def get_mapped_single_axis(self):
        """
        Returns linearized position converted into a segmented 1-D representation.
        
        Returns (pd.DataFrame): Segmented 1-D linear position.

        """

        invalid = self.query('@self.seg_idx.seg_idx == 0')
        invalid_flat = pd.DataFrame([[0, 0] for _ in range(len(invalid))],
                                    columns=['linpos_flat', 'linvel_flat'], index=invalid.index)

        center_flat = (self.query('@self.seg_idx.seg_idx == 1').
                       loc[:, [('lin_dist_well', 'well_center'),
                               ('lin_vel', 'well_center')]])
        center_flat[('lin_dist_well', 'well_center')] += self.arm_coord[0][0]
        left_flat = (self.query('@self.seg_idx.seg_idx == 2 | '
                                '@self.seg_idx.seg_idx == 3').
                     loc[:, [('lin_dist_well', 'well_left'),
                             ('lin_vel', 'well_left')]])
        left_flat[('lin_dist_well', 'well_left')] += self.arm_coord[1][0]
        right_flat = (self.query('@self.seg_idx.seg_idx == 4 | '
                                 '@self.seg_idx.seg_idx == 5').
                      loc[:, [('lin_dist_well', 'well_right'),
                              ('lin_vel', 'well_right')]])
        right_flat[('lin_dist_well', 'well_right')] += self.arm_coord[2][0]
        center_flat.columns = ['linpos_flat', 'linvel_flat']
        left_flat.columns = ['linpos_flat', 'linvel_flat']
        right_flat.columns = ['linpos_flat', 'linvel_flat']

        linpos_flat = pd.concat([invalid_flat, center_flat, left_flat, right_flat]) # type: pd.DataFrame
        linpos_flat = linpos_flat.sort_index()

        linpos_flat['seg_idx'] = self.seg_idx.seg_idx


        # reset history to remove intermediate query steps
        return FlatLinearPosition.create_default(linpos_flat, self.sampling_rate,
                                                 self.arm_coord, parent=self)

    def get_time_only_index(self):
        return self.reset_index(level=['day', 'epoch'])


class SpikeObservation(DayEpochTimeSeries):
    """
    The observations can be generated by the realtime system or from an offline encoding model.
    The observations consist of a panda table with one row for each spike being decoded.  Each
    spike (and observation) is identified by a unique timestamp and electrode id. The observation
    content is the estimated probability that the spike and its marks will be observed in the
    encoding model.
    """

    _metadata = DayEpochTimeSeries._metadata + ['observation_bin_size', 'parallel_bin_size']

    def __init__(self, data=None, index=None, columns=None, dtype=None, copy=False,
                 parent=None, history=None, sampling_rate=0, **kwds):
        super().__init__(data=data, index=index, columns=columns, dtype=dtype, copy=copy,
                         parent=parent, history=history, sampling_rate=sampling_rate, **kwds)
        self.parallel_bin_size = 0
        self.observation_bin_size = 0

    @classmethod
    def create_default(cls, df, sampling_rate, parent=None, **kwds):
        if parent is None:
            parent = df

        return cls(sampling_rate=sampling_rate, data=df, parent=parent, **kwds)

    @classmethod
    def from_realtime(cls, spike_dec, day, epoch, enc_settings, parent=None, **kwds):
        if parent is None:
            parent = spike_dec

        start_timestamp = spike_dec['timestamp'][0]
        spike_dec['time'] = spike_dec['timestamp'] / float(enc_settings.sampling_rate)
        return cls(sampling_rate=enc_settings.sampling_rate,
                   data=spike_dec.set_index(pd.MultiIndex.from_arrays([[day]*len(spike_dec), [epoch]*len(spike_dec),
                                                                       spike_dec['timestamp'], spike_dec['time']],
                                                                      names=['day', 'epoch', 'timestamp', 'time'])),
                   parent=parent, **kwds)

    def update_observations_bins(self, time_bin_size, inplace=False):
        if inplace:
            df = self
        else:
            df = self.copy()

        self.observation_bin_size = time_bin_size
        if self.parallel_bin_size % self.observation_bin_size != 0:
            raise DataFormatError('Parallel time bins must be a multiple of observation bin sizes.')

        dec_bins = np.floor((self.index.get_level_values('timestamp') -
                             self.index.get_level_values('timestamp')[0]) / time_bin_size).astype('int')
        dec_bins_start = (int(self.index.get_level_values('timestamp')[0] / time_bin_size) *
                          time_bin_size + dec_bins * time_bin_size)
        df['dec_bin'] = dec_bins
        df['dec_bin_start'] = dec_bins_start

        df.update_num_missing_future_bins(inplace=True)
        return df

    def update_parallel_bins(self, time_bin_size, inplace=True):
        if inplace:
            df = self
        else:
            df = self.copy()

        self.parallel_bin_size = time_bin_size

        if self.parallel_bin_size % self.observation_bin_size != 0:
            raise DataFormatError('Parallel time bins must be a multiple of observation bin sizes.')
        parallel_bins = np.floor((self.index.get_level_values('timestamp') -
                                  self.index.get_level_values('timestamp')[0]) / time_bin_size).astype('int')
        df['parallel_bin'] = parallel_bins

        return df

    def get_no_multi_index(self):
        return pd.DataFrame(self.set_index(self.index.get_level_values('timestamp')))

    def update_num_missing_future_bins(self, inplace=False):
        if inplace:
            df = self
        else:
            df = self.copy()
        df['num_missing_bins'] = np.concatenate([np.clip(np.diff(df['dec_bin'])-1, 0, None), [0]])

        return df


class Posteriors(DayEpochTimeSeries):

    _metadata = DayEpochTimeSeries._metadata + ['enc_settings']

    def __init__(self, data=None, index=None, columns=None, dtype=None, copy=False, parent=None, history=None,
                 sampling_rate=0, **kwds):

        try:
            self.enc_settings = kwds['enc_settings']
        except KeyError:
            self.enc_settings = None

        super().__init__(sampling_rate=sampling_rate, data=data, index=index, columns=columns,
                         dtype=dtype, copy=copy, parent=parent, history=history, **kwds)

    #@property
    #def _constructor(self):
    #    return functools.partial(type(self), history=self.history, **self.kwds)

    @classmethod
    def create_default(cls, df, enc_settings, dec_settings, parent=None, **kwds):
        if parent is None:
            parent = df

        return cls(df, parent=parent, enc_settings=enc_settings, dec_settings=dec_settings, **kwds)

    @classmethod
    def from_dataframe(cls, posterior: pd.DataFrame, encode_settings, dec_settings,
                       index=None, columns=None, parent=None, **kwds):
        if parent is None:
            parent = posterior

        if index is not None:
            posterior.set_index(index)
        if columns is not None:
            posterior.columns = columns
        return cls(data=posterior, parent=parent, enc_settings=encode_settings, dec_settings=dec_settings, **kwds)

    @classmethod
    def from_numpy(cls, posterior, day, epoch, timestamps, times, columns=None, parent=None, encode_settings=None):
        if parent is None:
            parent = posterior

        return cls(data=posterior, index=pd.MultiIndex.from_arrays([[day]*len(posterior), [epoch]*len(posterior),
                                                                    timestamps, times],
                                                                   names=['day', 'epoch', 'timestamp', 'time']),
                   columns=columns, parent=parent, enc_settings=encode_settings)

    @classmethod
    def from_realtime(cls, posterior: pd.DataFrame, day, epoch, columns=None, copy=False, parent=None,
                      enc_settings=None):
        if parent is None:
            parent = posterior

        if copy:
            posterior = posterior.copy()    # type: pd.DataFrame
        posterior.set_index(pd.MultiIndex.from_arrays([[day]*len(posterior), [epoch]*len(posterior),
                                                       posterior['timestamp'], posterior['timestamp']/
                                                       enc_settings.sampling_rate],
                                                      names=['day', 'epoch', 'timestamp', 'time']), inplace=True)

        if columns is not None:
            posterior.columns = columns

        return cls(data=posterior, parent=parent, enc_settings=enc_settings)

    def get_posteriors_as_np(self):
        return self[pos_col_format(0, self.kwds['enc_settings'].pos_num_bins):
                    pos_col_format(self.kwds['enc_settings'].pos_num_bins-1,
                                   self.kwds['enc_settings'].pos_num_bins)].values


    def get_distribution_view(self):
        return self.loc[:, pos_col_format(0, self.enc_settings.pos_num_bins):
                        pos_col_format(self.enc_settings.pos_num_bins-1, self.enc_settings.pos_num_bins)]

    def get_pos_range(self):
        return self.enc_settings.pos_bins[0], self.enc_settings.pos_bins[-1]

    def get_pos_start(self):
        return self.enc_settings.pos_bins[0]

    def get_pos_end(self):
        return self.enc_settings.pos_bins[-1]


class RippleTimes(DayEpochEvent):

    def __init__(self, data=None, index=None, columns=None, dtype=None, copy=False, parent=None, history=None, **kwds):
        super().__init__(data=data, index=index, columns=columns, dtype=dtype, copy=copy, parent=parent,
                         history=history, **kwds)

        if isinstance(data, pd.DataFrame):
            if not 'maxthresh' in data.columns:
                raise DataFormatError("RippleTimes must have 'maxthresh' column.")

    @classmethod
    def create_default(cls, df, time_unit: UnitTime, parent=None, **kwds):
        if parent is None:
            parent = df

        return cls(data=df, time_unit=time_unit, parent=parent, **kwds)

    def get_above_maxthresh(self, threshold):
        return self.query('maxthresh >= @threshold')


class StimLockout(DataFrameClass):

    _metadata = DataFrameClass._metadata

    def __init__(self, data=None, index=None, columns=None, dtype=None, copy=False, parent=None, history=None, **kwds):
        super().__init__(data, index, columns, dtype, copy, parent, history, **kwds)

    @classmethod
    def create_default(cls, df, sampling_rate, parent=None, **kwds):
        if parent is None:
            parent = df

        enc_settings = AttrDict({'sampling_rate': sampling_rate})
        return cls.from_realtime(df, enc_settings=enc_settings, parent=parent, **kwds)

    @classmethod
    def from_realtime(cls, stim_lockout, enc_settings, parent=None, **kwds):
        """
        Class factory to create stimulation lockout from realtime system.  
        Reshapes the structure to a more useful format (stim lockout intervals)
        Args:
            parent: 
            stim_lockout: Stim lockout pandas table from realtime records

        Returns: StimLockout

        """
        if parent is None:
            parent = stim_lockout

        stim_lockout_ranges = stim_lockout.pivot(index='lockout_num', columns='lockout_state', values='timestamp')
        stim_lockout_ranges = stim_lockout_ranges.reindex(columns=[1, 0])
        stim_lockout_ranges.columns = pd.MultiIndex.from_product([['timestamp'], ['on', 'off']])
        stim_lockout_ranges_sec = stim_lockout_ranges / float(enc_settings.sampling_rate)
        stim_lockout_ranges_sec.columns = pd.MultiIndex.from_product([['time'], ['on', 'off']])
        df = pd.concat([stim_lockout_ranges, stim_lockout_ranges_sec], axis=1)      # type: pd.DataFrame

        return cls(df, parent=parent, enc_settings=enc_settings, **kwds)

    def get_range_sec(self, low, high):
        sel = self.query('@self.time.off > @low and @self.time.on < @high')
        return type(self)(sel)


class FlatLinearPosition(LinearPosition):

    _metadata = LinearPosition._metadata + ['arm_coord']

    def __init__(self, data=None, index=None, columns=None, dtype=None,
                 copy=False, parent=None, history=None, sampling_rate=0, **kwds):
        super().__init__(sampling_rate=sampling_rate, data=data, index=index, columns=columns,
                         dtype=dtype, copy=copy, parent=parent, history=history, **kwds)

        #if isinstance(data, pd.DataFrame) and 'linvel_flat' not in data.columns:
        #   raise DataFormatError("Missing 'linvel_flat' column.")

    @classmethod
    def create_default(cls, df, sampling_rate, arm_coord, parent=None, **kwds):
        if parent is None:
            parent = df

        return cls(df, parent=parent, sampling_rate=sampling_rate, arm_coord=arm_coord, **kwds)

    @classmethod
    def from_nspike_posmat(cls, nspike_pos_data, enc_settings: EncodeSettings, parent=None):
        return LinearPosition.from_nspike_posmat(nspike_pos_data, enc_settings, parent).get_mapped_single_axis()


    @classmethod
    def from_numpy_single_epoch(cls, day, epoch, timestamp, lin_pos, lin_vel, sampling_rate, arm_coord):
        time = timestamp/float(sampling_rate)
        return cls(pd.DataFrame(list(zip(lin_pos, lin_vel)), columns=['linpos_flat', 'linvel_flat'],
                                index=pd.MultiIndex.from_arrays([[day]*len(timestamp), [epoch]*len(timestamp),
                                                                 timestamp, time],
                                                                names=['day', 'epoch', 'timestamp', 'time'])),
                   sampling_rate=sampling_rate, arm_coord=arm_coord)

    def get_above_velocity(self, threshold):

        # explicitly return copy convert weakref, for pickling
        return self.query('abs(linvel_flat) >= @threshold')

    def get_mapped_single_axis(self):
        return self

    def get_pd_no_multiindex(self):
        self.set_index(pd.Index(self.index.get_level_values('timestamp'), name='timestamp'))
