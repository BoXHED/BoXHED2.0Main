import os
import glob
from ctypes import *
import numpy as np
import pandas as pd

class preprocessor:

    class c_boundary_info (Structure):
        _fields_ = [("npatients", c_size_t), 
                    ("out_nrows", c_size_t), 
                    ("in_lbs",    c_void_p),
                    ("out_lbs",   c_void_p)]


    def __init__(self):
        #TODO: move compilation out of here!
        #print ("WARNING: not compiling preprocessor all over again...")

        os.system("python setup_preprocess.py build")
        #TODO: [0] causes problems if they have used multiple versions of python
        self.prep_libfile = glob.glob('build/*/preprocess*.so')[0]
        self.prep_lib = CDLL(self.prep_libfile)

        self.prep_lib.compute_quant.restype    = None
        self.prep_lib.compute_quant.argtypes   = [c_void_p, c_size_t, c_size_t, c_size_t, c_size_t, c_size_t, c_size_t, c_void_p, c_size_t, c_bool, c_int]

        self.prep_lib.get_boundaries.restype   = c_void_p
        self.prep_lib.get_boundaries.argtypes  = [c_void_p, c_size_t, c_size_t, c_size_t, c_size_t, c_size_t, c_size_t, c_void_p, c_size_t]

        self.prep_lib.preprocess.restype       = None
        self.prep_lib.preprocess.argtypes      = [c_void_p, c_size_t, c_size_t, c_void_p, c_void_p, c_void_p, c_size_t, c_size_t, c_size_t, c_size_t, c_size_t]

        self.prep_lib.free_boundary_info.restype  = None
        self.prep_lib.free_boundary_info.argtypes = [c_void_p]

        self.prep_lib.fix_data_on_boundaries.restype  = None
        self.prep_lib.fix_data_on_boundaries.argtypes = [c_void_p, c_size_t, c_size_t, c_void_p, c_void_p, c_size_t, c_int]
 

    def _get_col_indcs(self):
        self.t_start_idx = self.colnames.index('t_start')
        self.pat_idx     = self.colnames.index('patient')
        self.t_end_idx   = self.colnames.index('t_end')
        self.delta_idx   = self.colnames.index('delta') #TODO: either 0 or 1


    def _cnvrt_colnames(self):
        self.colnames[self.t_end_idx] = 'dt'
        #self.colnames.remove('patient')


    def _contig_float(self, arr):
        return np.ascontiguousarray(arr, dtype = np.float64)


    #TODO: can we have a parameter object to be accessed on the other side? rather than this??? this is so ugly
    def __compute_quant(self):
        self.prep_lib.compute_quant(c_void_p(self.data.ctypes.data), 
                                    c_size_t(self.nrows), 
                                    c_size_t(self.ncols), 
                                    c_size_t(self.t_start_idx), 
                                    c_size_t(self.t_end_idx), 
                                    #c_void_p(self.tpart.ctypes.data), 
                                    #c_size_t(self.tpart.size))
                                    c_size_t(self.pat_idx), 
                                    c_size_t(self.delta_idx), 
                                    c_void_p(self.quant.ctypes.data), 
                                    c_size_t(self.quant_per_column),
                                    c_bool(self.weighted),
                                    c_int(self.nthreads))


    def _get_boundaries(self):
        return self.c_boundary_info.from_address(self.prep_lib.get_boundaries(
            c_void_p(self.data.ctypes.data), 
            c_size_t(self.nrows), 
            c_size_t(self.ncols), 
            c_size_t(self.npatients), 
            c_size_t(self.pat_idx), 
            c_size_t(self.t_start_idx), 
            c_size_t(self.t_end_idx), 
            #c_void_p(self.tpart.ctypes.data), 
            #c_size_t(self.tpart.size)
            c_void_p(self.quant.ctypes.data), 
            c_size_t(self.quant_per_column)
            ))

    def _preprocess(self):
        self.preprocessed = self._contig_float(np.zeros((self.bndry_info.out_nrows, self.ncols))) 

        self.prep_lib.preprocess(
                c_void_p(self.data.ctypes.data),
                c_size_t(self.nrows), 
                c_size_t(self.ncols), 
                byref(self.bndry_info), 
                c_void_p(self.preprocessed.ctypes.data),

                #c_void_p(self.tpart.ctypes.data), 
                #c_size_t(self.tpart.size), 

                c_void_p(self.quant.ctypes.data), 
                c_size_t(self.quant_per_column), 


                c_size_t(self.t_start_idx), 
                c_size_t(self.t_end_idx), 
                c_size_t(self.delta_idx), 
                c_size_t(self.pat_idx), 
                c_size_t(self.nthreads))

    def _free_boundary_info(self):
        self.prep_lib.free_boundary_info(byref(self.bndry_info))
        del self.bndry_info

    def _prep_output_df(self):
        self._cnvrt_colnames(); 

        self.preprocessed = pd.DataFrame(self.preprocessed, columns = self.colnames)
        self.pats         = self.preprocessed['patient']
        self.y            = self.preprocessed[['delta', 'dt']]
        self.X            = self.preprocessed.drop(columns = ['patient', 'delta', 'dt'])
        
        #XXX: I will not drop this so that we can use sklearn group kfold for sklearn
        #self.preprocessed.drop(columns = ["patient"], inplace = True)


    def _set_lbs_ubs_ptrs(self):
        self.in_lbs   = (c_size_t * (self.bndry_info.npatients+1)).from_address(self.bndry_info.in_lbs)
        self.out_lbs  = (c_size_t * (self.bndry_info.npatients+1)).from_address(self.bndry_info.out_lbs)
    

    def _data_sanity_check(self):
        assert self.data.ndim==2,"ERROR: data needs to be 2 dimensional"
        assert self.data['patient'].between(1, self.npatients).all(),"ERROR: Patients need to be numbered from 1 to # patients"

    def _setup_data(self):

        #making sure patient data is contiguous
        self.data.sort_values(by=['patient', 't_start'], inplace = True)

        self.colnames  = list(self.data.columns)
        self.npatients = self.data['patient'].nunique()

        self._data_sanity_check()
        self._get_col_indcs()

        self.data  = self._contig_float(self.data)

     
    #def _compute_f0(self):
    #    self.f0 = np.log(np.sum(self.data[:,self.delta_idx])/np.sum(self.data[:,self.t_end_idx]-self.data[:,self.t_start_idx]))


    def _compute_quant(self):
        self.tpart = self._contig_float(np.zeros((1, self.quant_per_column)))
        self.quant = self._contig_float(np.zeros((1, self.quant_per_column*(self.ncols))))
        self.__compute_quant()

    def preprocess(self, data, quant_per_column=20, weighted=False, nthreads=-1):
        #TODO: maye change how the data is given? pat, X, y?

        #XXX: using np.float64---c_double
        self.nthreads           = nthreads
        self.quant_per_column   = min(quant_per_column, 256)
        self.weighted           = weighted
        self.data               = data
        self.nrows              = data.shape[0]
        self.ncols              = data.shape[1]

        self._setup_data()

        #self._compute_f0()

        self._compute_quant()

        self.bndry_info = self._get_boundaries()
        self._set_lbs_ubs_ptrs()

        #print (self.bndry_info)
        #print (self.quant)
        '''    
        for i in range(self.bndry_info.npatients):
            if (i>10):
                break
            print ("pat idx: ", i)
            print ("    range in input: ", self.in_lbs[i],  self.in_lbs[i+1]-1)
            print ("    range in output:", self.out_lbs[i], self.out_lbs[i+1]-1) 
        '''

        
        self._preprocess()

        self._prep_output_df()
        #print (self.preprocessed)

        self._free_boundary_info()

        #return self.f0, self.pats, self.X, self.y
        return self.pats, self.X, self.y

    def fix_data_on_boundaries(self, X, nthreads=-1):

        assert X.ndim==2,"ERROR: data needs to be 2 dimensional"
        nrows, ncols = X.shape
        assert ncols == self.ncols-3, "ERROR: ncols in X does not match the trained data"

        quant_idxs = np.ascontiguousarray(np.zeros(ncols), dtype = np.int32)

        for idx, colname in enumerate(X.columns):
            col_idx = self.colnames.index(colname)
            assert col_idx > -1, "ERROR: X and trained data colnames do not match"
            quant_idxs [idx] = col_idx


        processed = np.ascontiguousarray(X.values)

        #print ('data:')
        self.prep_lib.fix_data_on_boundaries(
            c_void_p(processed.ctypes.data),
            c_size_t(nrows),
            c_size_t(ncols),
            c_void_p(quant_idxs.ctypes.data),
            c_void_p(self.quant.ctypes.data),
            c_size_t(self.quant_per_column),
            c_int(nthreads))
        
        return processed
