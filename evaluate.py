from __future__ import print_function
import argparse
import os
import imp
import algorithms as alg
import utils

parser = argparse.ArgumentParser()
parser.add_argument('--config', type=str, required=True, default='',
    help='config file with parameters of the experiment. It is assumed that all'
         ' the config file is placed on  ')
parser.add_argument('--parent_exp', type=str, required=True, default=None)
parser.add_argument('--evaluate', default=False, action='store_true',
    help='If True, then no training is performed and the model is only '
         'evaluated on the validation or test set of MiniImageNet.')
parser.add_argument('--num_workers', type=int, default=4,
    help='number of data loading workers')
parser.add_argument('--cuda', type=bool, default=True, help='enables cuda')
parser.add_argument('--valset', default=False, action='store_true')
parser.add_argument('--exp_symlink_group', type=str, default=None)
parser.add_argument('--num_epochs', type=int, default=None)
parser.add_argument('--use_precomputed_features', action='store_true')
args_opt = parser.parse_args()

orig_cwd = os.path.abspath(os.getcwd())
os.chdir('experiments')
if not os.path.exists(args_opt.parent_exp):
    import glob
    glob_result = glob.glob(args_opt.parent_exp)
    assert len(glob_result) == 1
    args_opt.parent_exp = glob_result[0]
os.chdir(orig_cwd)

if args_opt.config.startswith('miniImageNet_') or args_opt.config.startswith('miniImageNetBase'):
    from dataloader import MiniImageNet, FewShotDataloader, load_data
    dataset_cls = MiniImageNet
    dataset_name = 'miniImageNet'
elif args_opt.config.startswith('FC100_') or args_opt.config.startswith('FC100Base'):
    from fc100_dataloader import FC100, FewShotDataloader, load_data
    dataset_cls = FC100
    dataset_name = 'FC100'
elif args_opt.config.startswith('CIFARFS_') or args_opt.config.startswith('CIFARFSBase'):
    from cifar_fs_dataloader import CIFAR_FS, FewShotDataloader, load_data
    dataset_cls = CIFAR_FS
    dataset_name = 'CIFAR_FS'
else:
    assert False

exp_name = 'EvalNaive___' + args_opt.config

exp_config_file = os.path.join('.', 'config', args_opt.config + '.py')
exp_directory = os.path.join('.', 'experiments', args_opt.parent_exp, exp_name)

feat_parent_exp, _ = args_opt.parent_exp.split(os.sep)

if args_opt.use_precomputed_features:
    feat_par_dir = os.path.join('.', 'experiments', feat_parent_exp, 'features')
    feat_dir = os.path.join(feat_par_dir, dataset_name)
    assert os.path.exists(feat_dir)
    def get_pickle_paths():
        dataset_pickle_paths = dataset_cls.get_pickle_paths()
        result = dict()
        for pkl_key in dataset_pickle_paths.keys():
            feat_pkl_path = os.path.join(feat_dir, pkl_key + '.pickle')
            assert os.path.exists(feat_pkl_path)
            result[pkl_key] = feat_pkl_path
        return result
else:
    get_pickle_paths = None

os.makedirs(exp_directory)
if args_opt.exp_symlink_group is not None:
    exp_group_dir = os.path.join('.', 'experiments', args_opt.parent_exp, args_opt.exp_symlink_group)
    try:
        os.makedirs(exp_group_dir)
    except:
        pass
    os.symlink(os.path.abspath(exp_directory), os.path.join(exp_group_dir, exp_name))

git_commit = utils.get_git_commit_hash()
print('Git commit: {}'.format(git_commit))
git_diff_file_path = os.path.join(exp_directory, 'git_diff_{}.patch'.format(git_commit))
utils.save_git_diff_to_file(git_diff_file_path)

for fname in os.listdir(os.path.join('.', 'experiments', args_opt.parent_exp)):
    if fname.startswith('classifier_') and fname.endswith('.best'):
        os.symlink(os.path.join('..', fname), os.path.join(exp_directory, fname))


# Load the configuration params of the experiment
print('Launching experiment: %s' % exp_config_file)
config = imp.load_source("",exp_config_file).config
config['exp_dir'] = exp_directory # the place where logs, models, and other stuff will be stored
for k in config['networks']:
    if config['networks'][k]['pretrained'] is not None:
        parts = config['networks'][k]['pretrained'].split(os.sep, 3)
        assert len(parts) == 4
        assert parts[0] == '.'
        assert parts[1] == 'experiments'
        if k == 'feat_model':
            parts[2] = feat_parent_exp
        elif k == 'classifier':
            parts[2] = args_opt.parent_exp
        else:
            assert False
        config['networks'][k]['pretrained'] = os.path.join(*parts)
print('Loading experiment %s from file: %s' %
      (args_opt.config, exp_config_file))
print('Generated logs, snapshots, and model files will be stored on %s' %
      (config['exp_dir']))

# Set train and test datasets and the corresponding data loaders
if not args_opt.valset:
    test_split = 'test'
    epoch_size = 600
else:
    test_split = 'val'
    epoch_size = 2000

if args_opt.num_epochs is not None:
    epoch_size = args_opt.num_epochs

data_test_opt = config['data_test_opt']
dloader_test = FewShotDataloader(
    dataset=dataset_cls(
            phase=test_split,
            get_pickle_paths=get_pickle_paths),
    nKnovel=data_test_opt['nKnovel'], # number of novel categories on each training episode.
    nKbase=data_test_opt['nKbase'], # number of base categories.
    nExemplars=data_test_opt['nExemplars'], # num training examples per novel category
    nTestNovel=data_test_opt['nTestNovel'], # num test examples for all the novel categories
    nTestBase=data_test_opt['nTestBase'], # num test examples for all the base categories
    batch_size=1,
    num_workers=0,
    epoch_size=epoch_size, # num of batches per epoch
)

algorithm = alg.FewShot(config)
if args_opt.cuda: # enable cuda
    algorithm.load_to_gpu()

# In evaluation mode we load the checkpoint with the highest novel category
# recognition accuracy on the validation set of MiniImagenet.
algorithm.load_checkpoint(epoch='*', train=False, suffix='.best')

# Run evaluation.
algorithm.evaluate(dloader_test, is_test=True)

