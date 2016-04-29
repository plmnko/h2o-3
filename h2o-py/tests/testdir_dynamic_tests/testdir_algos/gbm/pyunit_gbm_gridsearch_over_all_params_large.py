from __future__ import print_function

import sys
import random
import os
import numpy as np
import math
from builtins import range
import time
import json

sys.path.insert(1, "../../../../")

import h2o
from tests import pyunit_utils
from h2o.estimators.gbm import H2OGradientBoostingEstimator
from h2o.grid.grid_search import H2OGridSearch

class Test_gbm_grid_search:
    """
    PUBDEV-1843: Grid testing.  Subtask 2.

    This class is created to test the gridsearch for GBM algo and make sure it runs.  Only one test is performed
    here.

    Test Descriptions:
    test_gbm_grid_search_over_params performs the following:
        a. grab all truely griddable parameters and randomly or manually set the parameter values.
        b. Next, build H2O GBM models using grid search.  Count and make sure models
           are only built for hyper-parameters set to legal values.  No model is built for bad hyper-parameters
           values.  We should instead get a warning/error message printed out.
        c. For each model built using grid search, we will extract the parameters used in building
           that model and manually build a H2O GBM model.  MSEs are calculated from a test set
           to compare the performance of grid search model and our manually built model.  If their MSEs
           are close, declare test success.  Otherwise, declare test failure.
        d. we will check and make sure the models are built within the max_runtime_secs time limit that was set
           for it as well.  If max_runtime_secs was exceeded, declare test failure as well.

    Note that for hyper-parameters containing all legal parameter names and parameter value lists with legal
    and illegal values, grid-models should be built for all combinations of legal parameter values.  For
    illegal parameter values, a warning/error message should be printed out to warn the user but the
    program should not throw an exception;

    We will re-use the dataset generation methods for GLM.  There will be two type of datasets, one for regression and
    one for classification.
    """

    # parameters set by users, change with care
    max_col_count = 4               # set maximum values of train/test row and column counts
    max_col_count_ratio = 600       # set max row count to be multiples of col_count to avoid over fitting
    min_col_count_ratio = 300       # set min row count to be multiples of col_count to avoid over fitting

    max_p_value = 2                 # set maximum predictor value
    min_p_value = -2                # set minimum predictor value

    max_w_value = 2                 # set maximum weight value
    min_w_value = -2                # set minimum weight value

    max_class_number = 2           # maximum number of classes allowed

    max_grid_model = 10           # maximum number of grid models generated before adding max_runtime_secs

    class_number = 2                # number of response class for classification, randomly determined later

    curr_time = str(round(time.time()))     # store current timestamp, used as part of filenames.
    seed = round(time.time())

    # parameters denoting filenames of interested that store training/validation/test data sets in csv format
    training1_filename = "gridsearch_gbm_training1_"+curr_time+"_set.csv"
    json_filename = "gridsearch_gbm_hyper_parameter_" + curr_time + ".json"
    weight_filename = "gridsearch_"+curr_time+"_weight.csv"

    allowed_diff = 1e-2   # difference allow between grid search model and manually built model MSEs

    # System parameters, do not change.  Dire consequences may follow if you do
    current_dir = os.path.dirname(os.path.realpath(sys.argv[1]))    # directory of this test file

    noise_std = 0.01            # noise variance in Gaussian noise generation added to response
    noise_var = noise_std*noise_std     # Gaussian noise variance

    train_row_count = 0         # training data row count, randomly generated later
    train_col_count = 0         # training data column count, randomly generated later

    # following parameters are used to generate hyper-parameters
    max_int_val = 10            # maximum size of random integer values
    min_int_val = -2           # minimum size of random integer values
    max_int_number = 3          # maximum number of integer random grid values to generate

    max_real_val = 1            # maximum size of random float values
    min_real_val = -0.1           # minimum size of random float values
    max_real_number = 3         # maximum number of real grid values to generate

    time_scale = 1.2              # maximum runtime scale
    extra_time_fraction = 0.0   # since timing is never perfect, give some extra time on top of maximum runtime limit
    min_runtime_per_tree = 0    # minimum run time found.  Determined later
    model_run_time = 0.0        # time taken to run a vanilla GBM model.  Determined later.
    allowed_runtime_diff = 0.05     # run time difference between GBM manually built and gridsearch models before
                                    # we attempt to compare training metrics.

    # parameters denoting filenames with absolute paths
    training1_data_file = os.path.join(current_dir, training1_filename)
    weight_data_file = os.path.join(current_dir, weight_filename)

    families = ['gaussian', 'multinomial']    # distribution family to perform grid search over
    family = 'gaussian'     # choose default family to be gaussian
    training_metric = 'MSE'    # metrics by which we evaluate model performance

    test_name = "pyunit_gbm_gridsearch_over_all_params_large.py"     # name of this test
    sandbox_dir = ""  # sandbox directory where we are going to save our failed test data sets

    # store information about training/test data sets
    x_indices = []              # store predictor indices in the data set
    y_index = 0                 # store response index in the data set

    training1_data = []         # store training data sets
    test_failed = 0             # count total number of tests that have failed

    # give the user opportunity to pre-assign hyper parameters for fixed values
    hyper_params = dict()
    hyper_params["balance_classes"] = [True, False]
    hyper_params["fold_assignment"] = ["AUTO", "Random", "Modulo"]
    hyper_params["stopping_metric"] =["AUTO", "deviance", "MSE", "r2"]
    hyper_params["random_split_points"] = [True, False]

    # parameters to be excluded from hyper parameter list even though they may be gridable
    exclude_parameter_lists = ['distribution', 'tweedie_power', 'validation_frame', 'response_column',
                               'sample_rate_per_class']   # do not need these

    # these are supposed to be gridable but are not really
    exclude_parameter_lists.extend(['class_sampling_factors', 'fold_column', 'weights_column', 'offset_column',
                                    'build_tree_one_node', 'score_each_iteration', 'max_hit_ratio_k',
                                    'score_tree_interval', 'nbins_top_level'])

    params_zero_one = ['col_sample_rate', 'learn_rate_annealing', 'learn_rate', 'col_sample_rate_per_tree',
                       'sample_rate']
    params_more_than_zero = ['min_rows', 'max_depth',  "max_after_balance_size"]
    params_more_than_one = ['nbins_cats', 'nbins']
    params_zero_positive = ['max_runtime_secs', 'stopping_rounds', 'ntrees', 'stopping_tolerance']       # >= 0

    final_hyper_params = dict()     # store the final hyper-parameters that we are going to use
    gridable_parameters = []    # store griddable parameter names
    gridable_types = []         # store the corresponding griddable parameter types
    gridable_defaults = []      # store the gridabble parameter default values

    possible_number_models = 0      # possible number of models built based on hyper-parameter specification
    correct_model_number = 0        # count number of models built with bad hyper-parameter specification
    true_correct_model_number = 0   # count number of models built with good hyper-parameter specification
    nfolds = 5                      # enable cross validation to test fold_assignment

    def __init__(self):
        self.setup_data()
        self.setup_model()

    def setup_data(self):
        """
        This function performs all initializations necessary:
        1. generates all the random parameter values for our dynamic tests like the Gaussian
        noise std, column count and row count for training/test data sets.
        2. randomly choose the distribution family (gaussian, binomial, multinomial)
        to test.
        3. with the chosen distribution family, generate the appropriate data sets
        4. load the data sets and set the training set indices and response column index
        """

        # create and clean out the sandbox directory first
        self.sandbox_dir = pyunit_utils.make_Rsandbox_dir(self.current_dir, self.test_name, True)

        # randomly set Gaussian noise standard deviation as a fraction of actual predictor standard deviation
        self.noise_std = random.uniform(0, math.sqrt(pow((self.max_p_value - self.min_p_value), 2) / 12))
        self.noise_var = self.noise_std*self.noise_std

        # randomly determine data set size in terms of column and row counts
        self.train_col_count = random.randint(1, self.max_col_count)
        self.train_row_count = round(self.train_col_count * random.uniform(self.min_col_count_ratio,
                                                                           self.max_col_count_ratio))

        #  DEBUGGING setup_data, remember to comment them out once done.
        # self.train_col_count = 3
        # self.train_row_count = 200
        # self.max_real_number = 1
        # self.max_int_number = 1
        # end DEBUGGING

        # This is used to generate dataset for regression or classification.  Nothing to do
        # with setting the distribution family in this case
        
        # randomly choose which family of GBM algo to use
        self.family = self.families[random.randint(0, len(self.families)-1)]

        # set class number for classification
        if 'multinomial' in self.family:
            self.class_number = random.randint(2, self.max_class_number)    # randomly set number of classes K
            self.training_metric = 'logloss'

        # generate real value weight vector and training/validation/test data sets for GLM
        pyunit_utils.write_syn_floating_point_dataset_glm(self.training1_data_file, "",
                                                          "", self.weight_data_file,
                                                          self.train_row_count, self.train_col_count, 2,
                                                          self.max_p_value, self.min_p_value, self.max_w_value,
                                                          self.min_w_value, self.noise_std, self.family,
                                                          self.train_row_count, self.train_row_count,
                                                          class_number=self.class_number,
                                                          class_method=['probability', 'probability',
                                                                        'probability'])

        # preload data sets
        self.training1_data = h2o.import_file(pyunit_utils.locate(self.training1_data_file))

        # set data set indices for predictors and response
        self.y_index = self.training1_data.ncol-1
        self.x_indices = list(range(self.y_index))

        # set response to be categorical for classification tasks
        if 'multinomial' in self.family:
            self.training1_data[self.y_index] = self.training1_data[self.y_index].round().asfactor()

            # check to make sure all response classes are represented, otherwise, quit
            if self.training1_data[self.y_index].nlevels()[0] < self.class_number:
                print("Response classes are not represented in training dataset.")
                sys.exit(0)

        # save the training data files just in case the code crashed.
        pyunit_utils.remove_csv_files(self.current_dir, ".csv", action='copy', new_dir_path=self.sandbox_dir)

    def setup_model(self):
        """
        This function setup the gridsearch hyper-parameters that will be used later on:

        1. It will first try to grab all the parameters that are griddable and parameters used by GBM.
        2. It will find the intersection of parameters that are both griddable and used by GBM.
        3. There are several extra parameters that are used by GBM that are denoted as griddable but actually is not.
        These parameters have to be discovered manually and they These are captured in self.exclude_parameter_lists.
        4. We generate the gridsearch hyper-parameter.  For numerical parameters, we will generate those randomly.
        For enums, we will include all of them.

        :return: None
        """
        # build bare bone model to get all parameters
        model = H2OGradientBoostingEstimator(distribution=self.family, seed=self.seed, nfolds=self.nfolds)
        model.train(x=self.x_indices, y=self.y_index, training_frame=self.training1_data)

        self.model_run_time = pyunit_utils.find_grid_runtime([model])  # find model train time
        print("Time taken to build a base barebone model is {0}".format(self.model_run_time))

        summary_list = model._model_json["output"]["model_summary"]
        num_trees = summary_list.cell_values[0][summary_list.col_header.index('number_of_trees')]

        if num_trees == 0:
            self.min_runtime_per_tree = self.model_run_time
        else:
            self.min_runtime_per_tree = self.model_run_time / num_trees

        # grab all gridable parameters and its type
        (self.gridable_parameters, self.gridable_types, self.gridable_defaults) = \
            pyunit_utils.get_gridables(model._model_json["parameters"])

        # randomly generate griddable parameters including values outside legal range, like setting alpha values to
        # be outside legal range of 0 and 1 and etc
        (self.hyper_params, self.gridable_parameters, self.gridable_types, self.gridable_defaults) = \
            pyunit_utils.gen_grid_search(model.full_parameters.keys(), self.hyper_params,
                                         self.exclude_parameter_lists,
                                         self.gridable_parameters, self.gridable_types, self.gridable_defaults,
                                         random.randint(1, self.max_int_number),
                                         self.max_int_val, self.min_int_val,
                                         random.randint(1, self.max_real_number),
                                         self.max_real_val, self.min_real_val)

        # scale the max_runtime_secs parameters
        time_scale = self.time_scale * self.model_run_time
        if "max_runtime_secs" in list(self.hyper_params):
            self.hyper_params["max_runtime_secs"] = [time_scale * x for x
                                                     in self.hyper_params["max_runtime_secs"]]

        # generate a new final_hyper_params which only takes a subset of all griddable parameters while
        # hyper_params take all griddable parameters and generate the grid search hyper-parameters
        [self.possible_number_models, self.final_hyper_params] = \
            pyunit_utils.check_and_count_models(self.hyper_params, self.params_zero_one, self.params_more_than_zero,
                                                self.params_more_than_one, self.params_zero_positive,
                                                self.max_grid_model)

        # must add max_runtime_secs to restrict unit test run time and as a promise to Arno to test for this
        if ("max_runtime_secs" not in list(self.final_hyper_params)) and \
                ("max_runtime_secs" in list(self.hyper_params)):
            self.final_hyper_params["max_runtime_secs"] = self.hyper_params["max_runtime_secs"]
            len_good_time = len([x for x in self.hyper_params["max_runtime_secs"] if (x >= 0)])
            self.possible_number_models = self.possible_number_models*len_good_time

        # write out the hyper-parameters used into json files.
        pyunit_utils.write_hyper_parameters_json(self.current_dir, self.sandbox_dir, self.json_filename,
                                                 self.final_hyper_params)

    def tear_down(self):
        """
        This function performs teardown after the dynamic test is completed.  If all tests
        passed, it will delete all data sets generated since they can be quite large.  It
        will move the training/validation/test data sets into a Rsandbox directory so that
        we can re-run the failed test.
        """

        if self.test_failed:    # some tests have failed.  Need to save data sets for later re-runs
            # create Rsandbox directory to keep data sets and weight information
            self.sandbox_dir = pyunit_utils.make_Rsandbox_dir(self.current_dir, self.test_name, True)

            # Do not want to save all data sets.  Only save data sets that are needed for failed tests
            pyunit_utils.move_files(self.sandbox_dir, self.training1_data_file, self.training1_filename)

            # write out the jenkins job info into log files.
            json_file = os.path.join(self.sandbox_dir, self.json_filename)

            with open(json_file,'wb') as test_file:
                json.dump(self.hyper_params, test_file)
        else:   # all tests have passed.  Delete sandbox if if was not wiped before
            pyunit_utils.make_Rsandbox_dir(self.current_dir, self.test_name, False)

        # remove any csv files left in test directory
        pyunit_utils.remove_csv_files(self.current_dir, ".csv")
        pyunit_utils.remove_csv_files(self.current_dir, ".json")

    def test_gbm_grid_search_over_params(self):
        """
        test_gbm_grid_search_over_params: test for condition 1 and performs the following:
        a. grab all truely griddable parameters and randomly or manually set the parameter values.
        b. Next, build H2O GBM models using grid search.  Count and make sure models
           are only built for hyper-parameters set to legal values.  No model is built for bad hyper-parameters
           values.  We should instead get a warning/error message printed out.
        c. For each model built using grid search, we will extract the parameters used in building
           that model and manually build a H2O GBM model.  MSEs are calculated from a test set
           to compare the performance of grid search model and our manually built model.  If their MSEs
           are close, declare test success.  Otherwise, declare test failure.
        d. we will check and make sure the models are built within the max_runtime_secs time limit that was set
           for it as well.  If max_runtime_secs was exceeded, declare test failure as well.
        """

        print("*******************************************************************************************")
        print("test_gbm_grid_search_over_params for GBM " + self.family)
        h2o.cluster_info()

        try:
            print("Hyper-parameters used here is {0}".format(self.final_hyper_params))

            # start grid search
            grid_model = H2OGridSearch(H2OGradientBoostingEstimator(distribution=self.family, nfolds=self.nfolds,
                                                                    seed=self.seed),
                                       hyper_params=self.final_hyper_params)
            grid_model.train(x=self.x_indices, y=self.y_index, training_frame=self.training1_data)

            self.correct_model_number = len(grid_model)     # store number of models built

            # make sure the correct number of models are built by gridsearch
            if not (self.correct_model_number == self.possible_number_models):  # wrong grid model number
                self.test_failed += 1
                print("test_gbm_grid_search_over_params for GBM failed: number of models built by gridsearch "
                      "does not equal to all possible combinations of hyper-parameters")
            else:
                # add parameters into params_dict.  Use this to manually build model
                params_dict = dict()
                params_dict["distribution"] = self.family
                params_dict["nfolds"] = self.nfolds
                params_dict["seed"] = self.seed
                total_run_time_limits = 0.0   # calculate upper bound of max_runtime_secs
                true_run_time_limits = 0.0
                manual_run_runtime = 0.0

                # compare MSE performance of model built by gridsearch with manually built model
                for each_model in grid_model:

                    params_list = grid_model.get_hyperparams_dict(each_model._id)
                    params_list.update(params_dict)

                    model_params = dict()

                    # need to taken out max_runtime_secs from model parameters, it is now set in .train()
                    if "max_runtime_secs" in params_list:
                        model_params["max_runtime_secs"] = params_list["max_runtime_secs"]
                        max_runtime = params_list["max_runtime_secs"]
                        del params_list["max_runtime_secs"]
                    else:
                        max_runtime = 0

                    if "r2_stopping" in params_list:
                        model_params["r2_stopping"] = params_list["r2_stopping"]
                        del params_list["r2_stopping"]

                    if "validation_frame" in params_list:
                        model_params["validation_frame"] = params_list["validation_frame"]
                        del params_list["validation_frame"]

                    if "learn_rate_annealing" in params_list:
                        model_params["learn_rate_annealing"] = params_list["learn_rate_annealing"]
                        del params_list["learn_rate_annealing"]

                    # make sure manual model was provided the same max_runtime_secs as the grid model
                    each_model_runtime = pyunit_utils.find_grid_runtime([each_model])

                    manual_model = H2OGradientBoostingEstimator(**params_list)
                    manual_model.train(x=self.x_indices, y=self.y_index, training_frame=self.training1_data,
                                       **model_params)

                    # collect the time taken to manually built all models
                    model_runtime = pyunit_utils.find_grid_runtime([manual_model])  # time taken to build this model
                    manual_run_runtime += model_runtime

                    summary_list = manual_model._model_json['output']['model_summary']
                    tree_num = summary_list.cell_values[0][summary_list.col_header.index('number_of_trees')]

                    if max_runtime > 0:
                        # shortest possible time it takes to build this model
                        if (max_runtime < self.min_runtime_per_tree) or (tree_num <= 1):
                            total_run_time_limits += model_runtime
                        else:
                            total_run_time_limits += max_runtime

                    true_run_time_limits += max_runtime

                    # compute and compare test metrics between the two models
                    test_grid_model_metrics = each_model.model_performance()._metric_json[self.training_metric]
                    test_manual_model_metrics = manual_model.model_performance()._metric_json[self.training_metric]

                    # just compare the mse in this case within tolerance:
                    if (abs(model_runtime - each_model_runtime) < self.allowed_runtime_diff) and \
                            (abs(test_grid_model_metrics - test_manual_model_metrics) > self.allowed_diff):
                        self.test_failed += 1             # count total number of tests that have failed
                        print("test_gbm_grid_search_over_params for GBM failed: grid search model and manually "
                              "built H2O model differ too much in test MSE!")
                        break

                total_run_time_limits = max(total_run_time_limits, true_run_time_limits) * (1+self.extra_time_fraction)

                # make sure the max_runtime_secs is working to restrict model built time
                if not(manual_run_runtime <= total_run_time_limits):
                    self.test_failed += 1
                    print("test_gbm_grid_search_over_params for GBM failed: time taken to manually build models is {0}."
                          "  Maximum allowed time is {1}".format(manual_run_runtime, total_run_time_limits))

                if self.test_failed == 0:
                    print("test_gbm_grid_search_over_params for GBM has passed!")
        except:
            if self.possible_number_models > 0:
                print("test_gbm_grid_search_over_params for GBM failed: exception was thrown for no reason.")
                self.test_failed += 1


def test_grid_search_for_gbm_over_all_params():
    """
    Create and instantiate class and perform tests specified for GBM

    :return: None
    """
    test_gbm_grid = Test_gbm_grid_search()
    test_gbm_grid.test_gbm_grid_search_over_params()

    sys.stdout.flush()

    if test_gbm_grid.test_failed:  # exit with error if any tests have failed
        sys.exit(1)


if __name__ == "__main__":
    pyunit_utils.standalone_test(test_grid_search_for_gbm_over_all_params)
else:
    test_grid_search_for_gbm_over_all_params()
