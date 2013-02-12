# -*- coding: utf-8 -*-
# Copyright 2007-2011 The Hyperspy developers
#
# This file is part of  Hyperspy.
#
#  Hyperspy is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
#  Hyperspy is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with  Hyperspy.  If not, see <http://www.gnu.org/licenses/>.

import os

import numpy as np

from hyperspy.defaults_parser import preferences
from hyperspy.misc.utils import (incremental_filename,
                                  append2pathname,
                                  slugify)
from hyperspy.exceptions import NavigationDimensionError


class Parameter(object):
    """Model parameter
    
    Attributes
    ----------
    value : float or array
        The value of the parameter for the current location. The value
        for other locations is stored in map.
    bmin, bmax: float
        Lower and upper bounds of the parameter value.
    twin : {None, Parameter}
        If it is not None, the value of the current parameter is 
        a function of the given Parameter. The function is by default
        the identity function, but it can be defined by twin_function
    twin_function : function
        Function that, if selt.twin is not None, takes self.twin.value 
        as its only argument and returns a float or array that is 
        returned when getting Parameter.value
    twin_inverse_function : function
        The inverse of twin_function. If it is None then it is not 
        possible to set the value of the parameter twin by setting 
        the value of the current parameter.
    ext_force_positive : bool
        If True, the parameter value is set to be the absolute value 
        of the input value i.e. if we set Parameter.value = -3, the 
        value stored is 3 instead. This is useful to bound a value 
        to be positive in an optimization without actually using an 
        optimizer that supports bounding.
    ext_bounded : bool
        Similar to ext_force_positive, but in this case the bounds are
        defined by bmin and bmax. It is a better idea to use
        an optimizer that supports bounding though.
        
    Methods
    -------
    as_signal(field = 'values')
        Get a parameter map as a signal object
    plot()
        Plots the value of the Parameter at all locations.
    export(folder=None, name=None, format=None, save_std=False)
        Saves the value of the parameter map to the specified format
    connect, disconnect(function)
        Call the functions connected when the value attribute changes.
    
    
    """
    __number_of_elements = 1
    __value = 0
    _bounds = (None, None)
    component = None
    __twin = None
    _twins = []
    twin_function = lambda x: x
    twin_inverse_function = lambda x: x
    map = None
    connected_functions = list()
    _axes_manager = None
    __ext_bounded = False
    __ext_force_positive = False
    grad = None
    name = ''
    units = ''
    def __init__(self):
        self.value = 0      
        self.std = None
        self.free = True
    
    def __repr__(self):
        text = ''
        text += 'Parameter %s' % self.name
        if self.component is not None:
            text += ' of %s' % self.component._get_short_description()
        text = '<' + text + '>'
        return text
        
    def __len__(self):
        return self._number_of_elements
    
    def connect(self, f):
        if f not in self.connected_functions:
            self.connected_functions.append(f)
            if self.twin:
                self.twin.connect(f)
                
    def disconnect(self, f):
        if f in self.connected_functions:
            self.connected_functions.remove(f)
            if self.twin:
                self.twin.disconnect(f)
            
    def _getvalue(self):
        if self.twin is None:
            return self.__value
        else:
            return self.twin_function(self.twin.value)
    def _setvalue(self, arg):
        if hasattr(arg, "__len__"):
            if len(arg) != self._number_of_elements:
                raise ValueError(
                    "The lenght of the parameter must be ", 
                    self._number_of_elements)
            else:
                if not isinstance(arg, tuple):
                    arg = tuple(arg)
            
        elif self._number_of_elements != 1:
            raise ValueError(
                    "The lenght of the parameter must be ", 
                    self._number_of_elements)
        old_value = self.__value
                        
        if self.twin is not None:
            if self.twin_inverse_function is not None:
                self.twin.value = self.twin_inverse_function(arg)
            return

        if self.ext_bounded is False:
                self.__value = arg
        else:
            if self.ext_force_positive is True:
                arg = np.abs(arg)
            if self._number_of_elements == 1:
                if self.bmin is not None and arg <= self.bmin:
                    self.__value = self.bmin
                elif self.bmax is not None and arg >= self.bmax:
                    self.__value = self.bmax
                else:
                    self.__value = arg
            else:
                bmin = (self.bmin if self.bmin is not None 
                                  else -np.inf)
                bmax = (self.bmax if self.bmin is not None
                                  else np.inf)
                self.__value = np.clip(arg, bmin, bmax)

        if (self._number_of_elements != 1 and 
            not isinstance(self.__value, tuple)):
                self.__value = tuple(self.__value)
        if old_value != self.__value:
            for f in self.connected_functions:
                try:
                    f()
                except:
                    self.disconnect(f)
    value = property(_getvalue, _setvalue)
    
    # Fix the parameter when coupled
    def _getfree(self):
        if self.twin is None:
            return self.__free
        else:
            return False
    def _setfree(self,arg):
        self.__free = arg
        if self.component is not None:
            self.component._update_free_parameters()
    free = property(_getfree,_setfree)

    def _set_twin(self,arg):
        if arg is None:
            if self.__twin is not None:
                # Store the value of the twin in order to set the 
                # value of the parameter when it is uncoupled
                twin_value = self.value
                if self in self.__twin._twins:
                    self.__twin._twins.remove(self)
                    for f in self.connected_functions:
                        self.__twin.disconnect(f)
                # Setting the __value attribute directly avoids 
                # calling the functions connected to the parameter
                self.__value = twin_value
        else :
            if self not in arg._twins :
                arg._twins.append(self)
                for f in self.connected_functions:
                    arg.connect(f)                
        self.__twin = arg
        if self.component is not None:
            self.component._update_free_parameters()

    def _get_twin(self):
        return self.__twin
    twin = property(_get_twin, _set_twin)

    def _get_bmin(self):
        if self._number_of_elements == 1:
            return self._bounds[0]
        else:
            return self._bounds[0][0]
    def _set_bmin(self,arg):
        if self._number_of_elements == 1 :
            self._bounds = (arg,self.bmax)
        else:
            self._bounds = ((arg, self.bmax),)*self._number_of_elements
        # Update the value to take into account the new bounds
        self.value = self.value
    bmin = property(_get_bmin,_set_bmin)

    def _get_bmax(self):
        if self._number_of_elements == 1:
            return self._bounds[1]
        else:
            return self._bounds[0][1]
    def _set_bmax(self,arg):
        if self._number_of_elements == 1 :
            self._bounds = (self.bmin, arg)
        else:
            self._bounds = ((self.bmin, arg),)*self._number_of_elements
        # Update the value to take into account the new bounds
        self.value = self.value
    bmax = property(_get_bmax,_set_bmax)
    
    @property
    def _number_of_elements(self):
        return self.__number_of_elements
        
    @_number_of_elements.setter
    def _number_of_elements(self, arg):
        # Do nothing if the number of arguments stays the same
        if self.__number_of_elements == arg:
            return
        if arg <= 1:
            raise ValueError("Please provide an integer number equal "
                             "or greater to 1")
        self._bounds = ((self.bmin, self.bmax),) * arg
        self.__number_of_elements = arg

        if arg == 1:
            self._Parameter__value = 0
        else:
            self._Parameter__value = (0,) * arg
            
    @property
    def ext_bounded(self):
        return self.__ext_bounded
        
    @ext_bounded.setter
    def ext_bounded(self, arg):
        if arg is not self.__ext_bounded:
            self.__ext_bounded = arg
            # Update the value to take into account the new bounds
            self.value = self.value
            
    @property
    def ext_force_positive(self):
        return self.__ext_force_positive
        
    @ext_force_positive.setter
    def ext_force_positive(self, arg):
        if arg is not self.__ext_force_positive:
            self.__ext_force_positive = arg
            # Update the value to take into account the new bounds
            self.value = self.value

    def store_current_value_in_array(self,indexes):
        self.map['values'][indexes] = self.value
        self.map['is_set'][indexes] = True
        if self.std is not None:
            self.map['std'][indexes] = self.std
    def assign_current_value_to_all(self, mask=None):
        '''Stores in the map the current value for all the rest of the 
        pixels.
        
        Parameters
        ----------
        mask: numpy array
        
        '''
        if mask is None:
            mask = np.zeros(self.map.shape, dtype = 'bool')
        self.map['values'][mask == False] = self.value
        self.map['is_set'][mask == False] = True
        
    def create_array(self, shape):
        if len(shape) == 1 and shape[0] == 0:
            shape = [1,]
        dtype_ = np.dtype([
            ('values','float', self._number_of_elements), 
            ('std', 'float', self._number_of_elements), 
            ('is_set', 'bool', 1)])
        if (self.map is None  or self.map.shape != shape or 
                    self.map.dtype != dtype_):
            self.map = np.zeros(shape, dtype_)       
            self.map['std'][:] = np.nan
            # TODO: in the future this class should have access to 
            # axes manager and should be able to charge its own
            # values. Until then, the next line is necessary to avoid
            # erros when self.std is defined and the shape is different
            # from the newly defined arrays
            self.std = None
            
    def as_signal(self, field='values'):
        """Get a parameter map as a signal object.
        
        Please note that this method only works when the navigation 
        dimension is greater than 0.
        
        Parameters
        ----------
        field : {'values', 'std', 'is_set'}
        
        Raises
        ------
        
        NavigationDimensionError : if the navigation dimension is 0
        
        """
        from hyperspy.signal import Signal
        if self._axes_manager.navigation_dimension == 0:
            raise NavigationDimensionError(0, '>0')
            
        s = Signal(
            {'data' : self.map[field],
             'axes' : self._axes_manager._get_navigation_axes_dicts()})
        s.mapped_parameters.title = self.name
        for axis in s.axes_manager.axes:
            axis.navigate = False
        if self._number_of_elements > 1:
            s.axes_manager.append_axis(
                size=self._number_of_elements,
                name=self.name,
                index_in_array=len(s.axes_manager.axes),
                navigate=True)
        return s
        
    def plot(self):
        self.as_signal().plot()
        
    def export(self, folder=None, name=None, format=None,
               save_std=False):
        '''Save the data to a file.
        
        All the arguments are optional.
        
        Parameters
        ----------
        folder : str or None
            The path to the folder where the file will be saved.
             If `None` the current folder is used by default.
        name : str or None
            The name of the file. If `None` the Components name followed
             by the Parameter `name` attributes will be used by default.
              If a file with the same name exists the name will be 
              modified by appending a number to the file path.
        save_std : bool
            If True, also the standard deviation will be saved
        
        '''
        if format is None:
            format = preferences.General.default_export_format
        if name is None:
            name = self.component.name + '_' + self.name
        filename = incremental_filename(slugify(name) + '.' + format)
        if folder is not None:
            filename = os.path.join(folder, filename)
        self.as_signal().save(filename)
        if save_std is True:
            self.as_signal(field = 'std').save(append2pathname(
                filename,'_std'))
                    
class Component(object):
    def __init__(self, parameter_name_list):
        self.connected_functions = list()
        self.parameters = []
        self.init_parameters(parameter_name_list)
        self._update_free_parameters()
        self.active = True
        self.isbackground = False
        self.convolved = True
        self.parameters = tuple(self.parameters)
        self.name = ''
        self._id_name = self.__class__.__name__
        self._id_version = '1.0'
        self._position = None
        
    def connect(self, f):
        if f not in self.connected_functions:
            self.connected_functions.append(f)
    def disconnect(self, f):
        if f in self.connected_functions:
            self.connected_functions.remove(f)
            
    def _get_active(self):
        return self.__active
    def _set_active(self, arg):
        self.__active = arg
        for f in self.connected_functions:
            try:
                f()
            except:
                self.disconnect(f)
    active = property(_get_active, _set_active)

    def init_parameters(self, parameter_name_list):
        for name in parameter_name_list:
            parameter = Parameter()
            self.parameters.append(parameter)
            parameter.name = name
            setattr(self, name, parameter)
            if hasattr(self, 'grad_' + name):
                parameter.grad = getattr(self, 'grad_' + name)
            parameter.component = self
            
    def _get_long_description(self):
        if self.name:
            text = '%s (%s component)' % (self.name, self._id_name)
        else:
            text = '%s component' % self._id_name
        return text
        
    def _get_short_description(self):
        text = ''
        if self.name:
            text += self.name
        else:
            text += self._id_name
        text += ' component'
        return text
    
    def __repr__(self):
        text = '<%s>' % self._get_long_description()
        return text

    def _update_free_parameters(self):
        self.free_parameters = set()
        for parameter in self.parameters:
            if parameter.free:
                self.free_parameters.add(parameter)
        # update_number_free_parameters(self):
        i=0
        for parameter in self.free_parameters:
            i += parameter._number_of_elements
        self._nfree_param=i

    def update_number_parameters(self):
        i=0
        for parameter in self.parameters:
            i += parameter._number_of_elements
        self.nparam=i

    def charge(self, p, p_std = None, onlyfree = False):
        if onlyfree is True:
            parameters = self.free_parameters
        else:
            parameters = self.parameters
        i=0
        for parameter in parameters:
            lenght = parameter._number_of_elements
            parameter.value = (p[i] if lenght == 1 else 
            p[i:i+lenght].tolist())
            if p_std is not None:
                parameter.std = (p_std[i] if lenght == 1 else 
                p_std[i:i+lenght].tolist())
            
            i+=lenght           
                
    def create_arrays(self, shape):
        for parameter in self.parameters:
            parameter.create_array(shape)
    
    def store_current_parameters_in_map(self, indexes):
        # If it is a single spectrum indexes is () 
        if not indexes:
            indexes = (0,)
        for parameter in self.parameters:
            parameter.store_current_value_in_array(indexes)
        
    def charge_value_from_map(self, indexes, only_fixed=False):
        # If it is a single spectrum indexes is () 
        if not indexes:
            indexes = (0,)
        if only_fixed is True:
            parameters = set(self.parameters) - set(
                                                   self.free_parameters)
        else:
            parameters = self.parameters
        parameters = [parameter for parameter in parameters
                      if parameter.twin is None]
        for parameter in parameters:
            if parameter.map['is_set'][indexes]:
                parameter.value = parameter.map['values'][indexes]
                parameter.std = parameter.map['std'][indexes]

    def plot(self, only_free = True):
        """Plot the value of the parameters of the model
        
        Parameters
        ----------
        only_free : bool
            If True, only the value of the parameters that are free will
             be plotted
              
        """
        if only_free:
            parameters = self.free_parameters
        else:
            parameters = self.parameters
            
        parameters = [k for k in parameters if k.twin is None]
        for parameter in parameters:
            parameter.plot()
            
    def export(self, folder=None, format=None, save_std=False,
               only_free=True):
        """Plot the value of the parameters of the model
        
        Parameters
        ----------
        folder : str or None
            The path to the folder where the file will be saved. If 
            `None` the
            current folder is used by default.
        format : str
            The format to which the data will be exported. It must be 
            the
            extension of any format supported by Hyperspy. If None, the 
            default
            format for exporting as defined in the `Preferences` will be
             used.
        save_std : bool
            If True, also the standard deviation will be saved.
        only_free : bool
            If True, only the value of the parameters that are free will
             be
            exported.
            
        Notes
        -----
        The name of the files will be determined by each the Component 
        and
        each Parameter name attributes. Therefore, it is possible to 
        customise
        the file names modify the name attributes.
              
        """
        if only_free:
            parameters = self.free_parameters
        else:
            parameters = self.parameters
            
        parameters = [k for k in parameters if k.twin is None]
        for parameter in parameters:
            parameter.export(folder=folder, format=format,
                             save_std=save_std,)
            
    def summary(self):
        for parameter in self.parameters:
            dim = len(parameter.map.squeeze().shape) if parameter.map \
                        is not None else 0
            if parameter.twin is None:
                if dim <= 1:
                    print '%s = %s ± %s %s' % (parameter.name,
                                               parameter.value, 
                                               parameter.std,
                                               parameter.units)

    def __call__(self, p, x, onlyfree = True) :
        self.charge(p , onlyfree = onlyfree)
        return self.function(x)
        
    def set_axes(self, axes_manager):
        for parameter in self.parameters:
            parameter._axes_manager = axes_manager
