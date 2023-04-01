import numpy as np
import os
import scipy.sparse as sparse
import pickle
from .features import SparseFeatures, DenseFeatures
from .labels import LabelsBase


class DataloaderBase(object):
    """Base Dataloader for extreme classifiers
    Works for sparse and dense features
    Parameters:
    -----------
    data_dir: str
        data directory with all files
    dataset: str
        Name of the dataset; like EURLex-4K
    feat_fname: str
        File name of training feature file
        Should be in sparse format with header
    label_fname: str
        File name of training label file
        Should be in sparse format with header
    batch_size: int, optional, default=1000
        train these many classifiers in parallel
    feature_type: str, optional, default='sparse'
        feature type: sparse or dense
    mode: str, optional, default='train'
        train or predict
        - remove invalid labels in train
    batch_order: str, optional, default='labels'
        iterate over labels or instances
    norm: str, optional, default='l2'
        normalize features
    start_index: int, optional, default=0
        start training from this labels index
    end_index: int, optional, default=-1
        train till this labels index
    """

    def __init__(self, data_dir, dataset, feat_fname, label_fname,
                 batch_size, feature_type, mode='train',
                 batch_order='labels', norm='l2', start_index=0,
                 end_index=-1):
        # TODO Option to load only features; useful in prediction
        self.feature_type = feature_type
        self.norm = norm
        self.features, self.labels = None, None
        self.batch_size = batch_size
        self.start_index = start_index
        self.end_index = end_index
        self.batch_order = batch_order
        self.mode = mode
        self.valid_labels = None
        self.num_valid_labels = None
        self.batches = None
        self.construct(data_dir, dataset, feat_fname, label_fname)

    def load_features(self, data_dir, fname):
        """Load features from given file
        """
        if self.feature_type == 'sparse':
            return SparseFeatures(data_dir, fname)
        elif self.feature_type == 'dense':
            return DenseFeatures(data_dir, fname)
        else:
            raise NotImplementedError("Unknown feature type!")

    def load_labels(self, data_dir, fname):
        """Load labels from given file
        Labels can also be supplied directly
        """
        # Pass dummy labels if required
        _format = 'csc' if self.batch_order == 'labels' else 'csr'
        return LabelsBase(data_dir, fname, _format=_format)

    def load_data(self, data_dir, fname_f, fname_l):
        """Load features and labels from file in libsvm format or pickle
        """
        labels = self.load_labels(data_dir, fname_l)
        features = self.load_features(data_dir, fname_f)
        if self.norm is not None:
            features.normalize(norm=self.norm)
        return features, labels

    @property
    def num_instances(self):
        return self.features.num_instances

    @property
    def num_features(self):
        return self.features.num_features

    @property
    def num_labels(self):
        return self.labels.num_labels

    def get_stats(self):
        """Get dataset statistics
        """
        return self.num_instances, self.num_features, self.num_labels

    def construct(self, data_dir, dataset, feat_fname, label_fname):
        data_dir = os.path.join(data_dir, dataset)
        self.features, self.labels = self.load_data(
            data_dir, feat_fname, label_fname)
        self.num_labels_ = self.labels.Y.shape[1]   # Original number of labels
        if self.mode == 'train':
            if self.start_index != 0 or self.end_index != -1:
                self.end_index = self.num_labels \
                    if self.end_index == -1 else self.end_index
                self.labels = self.labels[:, self.start_index: self.end_index]
            self.valid_labels = self.labels.remove_invalid()
        self._gen_batches()

    def _create_instance_batch(self, batch_indices):
        return {
            'data': self.features.data,
            'ind': batch_indices,
            'Y': self.labels.index_select(batch_indices, axis=0),
        }

    def _gen_batches(self):
        if self.batch_order == 'labels':
            offset = 0 if self.num_labels % self.batch_size == 0 else 1
            num_batches = self.num_labels//self.batch_size + offset
            self.batches = np.array_split(
                np.arange(self.num_labels), num_batches)
        elif self.batch_order == 'instances':
            offset = 0 if self.num_instances % self.batch_size == 0 else 1
            num_batches = self.num_instances//self.batch_size + offset
            self.batches = np.array_split(
                np.arange(self.num_instances), num_batches)
        else:
            raise NotImplementedError("Unknown order for batching!")

    def save(self, fname):
        state = {'num_labels': self.num_labels,
                 'num_labels_': self.num_labels_,
                 'valid_labels': self.valid_labels
                 }
        pickle.dump(state, open(fname, 'wb'))

    def load(self, fname):
        state = pickle.load(open(fname, 'rb'))
        self.num_labels = state['num_labels']
        self.num_labels_ = state['num_labels_']
        self.valid_labels = state['valid_labels']

    def __len__(self):
        return self.num_batches

    @property
    def num_batches(self):
        return len(self.batches)  # Number of batches


class Dataloader(DataloaderBase):
    """ Dataloader for 1-vs-all extreme classifiers
    Works for sparse and dense features
    Parameters:
    -----------
    data_dir: str
        data directory with all files
    dataset: str
        Name of the dataset; like EURLex-4K
    feat_fname: str
        File name of training feature file
        Should be in sparse format with header
    label_fname: str
        File name of training label file
        Should be in sparse format with header
    batch_size: int, optional, default=1000
        train these many classifiers in parallel
    feature_type: str, optional, default='sparse'
        feature type: sparse or dense
    mode: str, optional, default='train'
        train or predict
        - remove invalid labels in train
    batch_order: str, optional, default='labels'
        iterate over labels or instances
    norm: str, optional, default='l2'
        normalize features
    start_index: int, optional, default=0
        start training from this labels index
    end_index: int, optional, default=-1
        train till this labels index
    """

    def __init__(self, data_dir, dataset, feat_fname, label_fname,
                 batch_size, feature_type, mode='train',
                 batch_order='labels', norm='l2', start_index=0,
                 end_index=-1):
        super().__init__(data_dir, dataset, feat_fname, label_fname,
                         batch_size, feature_type, mode, batch_order, norm,
                         start_index, end_index)

    def _create_label_batch(self, batch_indices):
        batch_data = []
        for idx in batch_indices:
            pos_indices = self.labels.index_select(idx).indices
            batch_labels = -1*np.ones((self.num_instances,), dtype=np.float32)
            batch_labels[pos_indices] = 1
            item = {'ind': None, 'data': self.features.data, 'Y': batch_labels}
            batch_data.append(item)
        return batch_data

    def _create_batch(self, batch_indices):
        if self.batch_order == 'labels':
            return self._create_label_batch(batch_indices)
        else:
            return self._create_instance_batch(batch_indices)

    def __iter__(self):
        for batch_indices in self.batches:
            yield self._create_batch(batch_indices)


class DataloaderShortlist(DataloaderBase):
    """Dataloader for extreme classifiers with extreme shortlist
    Works for sparse and dense features
    Parameters:
    -----------
    data_dir: str
        data directory with all files
    dataset: str
        Name of the dataset; like EURLex-4K
    feat_fname: str
        File name of training feature file
        Should be in sparse format with header
    label_fname: str
        File name of training label file
        Should be in sparse format with header
    batch_size: int, optional, default=1000
        train these many classifiers in parallel
    feature_type: str, optional, default='sparse'
        feature type: sparse or dense
    mode: str, optional, default='train'
        train or predict
        - remove invalid labels in train
    batch_order: str, optional, default='labels'
        iterate over labels or instances
    norm: str, optional, default='l2'
        normalize features
    start_index: int, optional, default=0
        start training from this labels index
    end_index: int, optional, default=-1
        train till this labels index
    """

    def __init__(self, data_dir, dataset, feat_fname, label_fname,
                 batch_size, feature_type, mode='train',
                 batch_order='labels', norm='l2', start_index=0,
                 end_index=-1):
        # TODO Option to load only features; useful in prediction
        super().__init__(data_dir, dataset, feat_fname, label_fname,
                         batch_size, feature_type, mode, batch_order, norm,
                         start_index, end_index)

    def _create_label_batch(self, batch_indices):
        batch_data = []
        for idx in batch_indices:
            item = {'data': self.features.data}
            #  TODO Check if this could be done more efficiently
            temp = self.labels.index_select(idx)
            item['ind'] = temp.indices
            item['Y'] = temp.data
            batch_data.append(item)
        return batch_data

    def _create_batch(self, batch_indices):
        if self.batch_order == 'labels':
            return self._create_label_batch(batch_indices)
        else:
            return self._create_instance_batch(batch_indices)

    def update_data_shortlist(self, shortlist_ind, shortlist_sim):
        # TODO Remove this loop
        _labels = self.labels.data.tolil()
        pos_labels = _labels.rows  # Avoid this?
        rows = []
        cols = []
        data = []
        for idx in range(self.num_instances):
            indices = shortlist_ind[idx]
            _pos = pos_labels[idx]
            s_pos = set(_pos)
            s_pos.update([self.num_labels])
            _neg = list(filter(lambda x: x not in s_pos, indices))
            num_pos, num_neg = len(_pos), len(_neg)
            data.extend([1]*num_pos + [-1]*num_neg)
            cols.extend(_pos + _neg)
            rows.extend([idx]*(num_pos+num_neg))
        self.labels.data = sparse.csc_matrix(
            (data, (rows, cols)), shape=(self.num_instances, self.num_labels))

    def __iter__(self):
        for batch_indices in self.batches:
            yield self._create_batch(batch_indices)
