#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright © 2018 Michael J. Hayford
""" Interactive 2D lens picture

    The Lens Layout capability provides a 2D display of the optical model
    represented by **shapes**. Shapes contain the `dict`
        handles dict: named graphic handles for different aspects of the
                      parent object
        actions dict: functions for press, drag, and release actions

.. Created on Tue Sep 18 14:23:28 2018

.. codeauthor: Michael J. Hayford
"""

import numpy as np

from rayoptics.optical import elements
from rayoptics.optical import gap
from rayoptics.optical import transform
from rayoptics.optical.trace import (trace_boundary_rays_at_field,
                                     boundary_ray_dict, RaySeg)
from rayoptics.gui import appcmds


def setup_shift_of_ray_bundle(seq_model, start_offset):
    """ compute transformation for rays "start_offset" from 1st surface

    Args:
        seq_model: the sequential model
        start_offset: z distance rays should start wrt first surface.
                      positive if to left of first surface
    Returns:
        transformation rotation and translation::
            (rot, t)
    """

    s1 = seq_model.ifcs[1]
    s0 = seq_model.ifcs[0]
    g0 = gap.Gap(start_offset, seq_model.gaps[0].medium)
    rot, t = transform.reverse_transform(s0, g0, s1)
    return rot, t


def shift_start_of_ray_bundle(start_bundle, ray_bundle, rot, t):
    """ modify ray_bundle so that rays begin "start_offset" from 1st surface

    Args:
        ray_bundle: list of rays in a bundle, i.e. all for one field.
                    ray_bundle[0] is assumed to be the chief ray
        start_offset: z distance rays should start wrt first surface.
                      positive if to left of first surface
        rot: transformation rotation
        t: transformation translation
    """

    for ri, r in enumerate(ray_bundle):
        b4_pt = rot.dot(r.ray[1].p) - t
        b4_dir = rot.dot(r.ray[0].d)
        if ri == 0:
            # For the chief ray, use the input offset.
            dst = -b4_pt[2]/b4_dir[2]
        else:
            pt0 = start_bundle[0].p
            dir0 = start_bundle[0].d
            # Calculate distance along ray to plane perpendicular to
            #  the chief ray.
            dst = -(b4_pt - pt0).dot(dir0)/b4_dir.dot(dir0)
        pt = b4_pt + dst*b4_dir
        ray0 = RaySeg(pt, b4_dir, dst, r.ray[0].nrml)
        start_bundle[ri] = ray0


def transform_ray_seg(poly, r, tfrm):
    rot, trns = tfrm
    p = rot.dot(r.p) + trns
    poly.append([p[2], p[1]])


def bbox_from_poly(poly):
    minx, miny = np.min(poly, axis=0)
    maxx, maxy = np.max(poly, axis=0)
    return np.array([[minx, miny], [maxx, maxy]])


def scale_bounds(bbox, oversize_factor):
    inc_x = oversize_factor*(bbox[1][0] - bbox[0][0])
    inc_y = oversize_factor*(bbox[1][1] - bbox[0][1])
    incr = max(inc_x, inc_y)
    return np.array([[bbox[0][0]-incr, bbox[0][1]-incr],
                     [bbox[1][0]+incr, bbox[1][1]+incr]])


def transform_poly(tfrm, poly):
        coord_flip = np.array([[0., 1.], [1., 0.]])

        poly = np.matmul(coord_flip, poly.T)
        poly = np.matmul(tfrm[0][1:, 1:], poly).T

        t = np.array([tfrm[1][1], tfrm[1][2]])
        poly += t

        # flip coordinates back to 2D plot coordinates, +y points up
        poly = np.matmul(poly, coord_flip)
        bbox = bbox_from_poly(poly)
        return poly, bbox


def inv_transform_poly(tfrm, poly):
        coord_flip = np.array([[0., 1.], [1., 0.]])
        poly = np.matmul(coord_flip, poly.T)

        t = np.array([tfrm[1][1], tfrm[1][2]])
        poly -= t

        poly = np.matmul(tfrm[0][1:, 1:], poly).T

        # flip coordinates back to 2D plot coordinates, +y points up
        poly = np.matmul(poly, coord_flip)
        return poly


def create_optical_element(opt_model, e):
    if isinstance(e, elements.Element):
        return LensElement(opt_model, e)
    elif isinstance(e, elements.Mirror):
        return MirrorElement(opt_model, e)
    else:
        return OpticalElement(opt_model, e)


class OpticalElement():
    def __init__(self, opt_model, e):
        self.opt_model = opt_model
        self.e = e
        self.handles = {}
        self.actions = self.edit_shape_actions()
        self.handle_actions = self.e.handle_actions()

    def update_shape(self, view):
        self.e.render_handles(self.opt_model)
        for key, value in self.e.handles.items():
            poly = np.array(value[0])
            poly_gbl, bbox = transform_poly(value[1], poly)
            if value[2] == 'polygon':
                p = view.create_polygon(poly_gbl, self.render_color(),
                                        zorder=2.5)
            elif value[2] == 'polyline':
                p = view.create_polyline(poly_gbl)
            else:
                break
            self.handles[key] = (p, bbox)
        return self.handles

    def render_color(self):
        return self.e.render_color

    def get_label(self):
        if not hasattr(self.e, 'label'):
            self.e.label = 'element'
        return self.e.label

    def edit_shape_actions(self):
        actions = {}

        def on_select_shape(fig, handle, event):
            handle_actions = self.handle_actions[handle]
            for key, action_obj in handle_actions.items():
                action_obj.actions['press'](fig, event)
            self.select_pt = ((event.x, event.y), (event.xdata, event.ydata))
#            print('select pt:', self.select_pt)
#            print('select pt:', event.x, event.y)

        actions['press'] = on_select_shape

        def on_edit_shape(fig, handle, event):
            handle_actions = self.handle_actions[handle]
            x, y = self.select_pt[0]
            xdata, ydata = self.select_pt[1]
            delta_x, delta_y = abs(x - event.x), abs(y - event.y)
            delta_xdata, delta_ydata = (abs(xdata - event.xdata),
                                        abs(ydata - event.ydata))
            if self.move_direction is None:
                if delta_x > delta_y:
                    self.move_direction = 'x'
#                    print('move horizontal: delta x, y:', delta_x, delta_y,
#                          delta_xdata, delta_ydata)
                elif delta_x < delta_y:
                    self.move_direction = 'y'
#                    print('move vertical: delta x, y:', delta_x, delta_y,
#                          delta_xdata, delta_ydata)
                else:
                    self.move_direction = None
#                    print('move same: delta x, y:', delta_x, delta_y)

            gbl_pt = np.array([event.xdata, event.ydata])
            lcl_pt = inv_transform_poly(self.e.handles[handle][1], gbl_pt)
            dxdy = event.xdata - xdata, event.ydata - ydata
#            print('move pt:', event.xdata, event.ydata, lcl_pt)
            if 'pt' in handle_actions:
                if 'drag' in handle_actions['pt'].actions:
                    handle_actions['pt'].actions['drag'](fig, event, lcl_pt)
            elif self.move_direction in handle_actions:
                if 'drag' in handle_actions[self.move_direction].actions:
                    if self.move_direction == 'x':
                        handle_actions['x'].actions['drag'](fig, event,
                                                            dxdy[0])
                    elif self.move_direction == 'y':
                        handle_actions['y'].actions['drag'](fig, event,
                                                            dxdy[1])

            fig.refresh_gui()

        actions['drag'] = on_edit_shape

        def on_release_shape(fig, handle, event):
            print('release pt:', event.x, event.y)
            handle_actions = self.handle_actions[handle]
            for key, action_obj in handle_actions.items():
                action_obj.actions['release'](fig, event)
            self.select_pt = None
            self.move_direction = None
#            fig.refresh_gui()

        actions['release'] = on_release_shape

        return actions


class LensElement(OpticalElement):
    def __init__(self, opt_model, e):
        super().__init__(opt_model, e)
        self.select_pt = None
        self.move_direction = None

    def get_label(self):
        if not hasattr(self.e, 'label'):
            self.e.label = 'lens'
        return self.e.label


class MirrorElement(OpticalElement):
    def __init__(self, opt_model, e):
        super().__init__(opt_model, e)

    def get_label(self):
        if not hasattr(self.e, 'label'):
            self.e.label = 'mirror'
        return self.e.label


class RayBundle():
    """ class for ray bundle from a single field point """
    def __init__(self, opt_model, fld, fld_label, wvl, start_offset,
                 ray_table_callback=None):
        self.opt_model = opt_model
        self.fld = fld
        self.fld_label = fld_label
        self.wvl = wvl
        self.start_offset = start_offset
        self.handles = {}
        self.actions = self.edit_ray_bundle_actions()
        self.ray_table_callback = ray_table_callback

    def get_label(self):
        return self.fld_label

    def render_ray(self, ray, start_seg, tfrms):
        poly = []
        transform_ray_seg(poly, start_seg, tfrms[0])
        for i, r in enumerate(ray[1:], 1):
            transform_ray_seg(poly, r, tfrms[i])
        return np.array(poly)

    def render_shape(self, rayset, start_bundle, tfrms):
        poly1 = []
        transform_ray_seg(poly1, start_bundle[3], tfrms[0])
        for i, r in enumerate(rayset['+Y'].ray[1:], 1):
            transform_ray_seg(poly1, r, tfrms[i])

        poly2 = []
        transform_ray_seg(poly2, start_bundle[4], tfrms[0])
        for i, r in enumerate(rayset['-Y'].ray[1:], 1):
            transform_ray_seg(poly2, r, tfrms[i])

        poly2.reverse()
        poly1.extend(poly2)
        bbox = bbox_from_poly(poly1)
        return poly1, bbox

    def update_shape(self, view):
        rndr_clr = [254, 197, 254, 64]  # magenta, 25%
        wvl = self.opt_model.optical_spec.spectral_region.central_wvl
        self.wvl = wvl
        rayset = trace_boundary_rays_at_field(self.opt_model,
                                              self.fld, wvl,
                                              use_named_tuples=True)

        self.rayset = boundary_ray_dict(self.opt_model, rayset)
        # If the object distance (tfrms[0][1][2]) is greater than the
        #  start_offset, then modify rayset start to match start_offset.
        # Remember object transformation for resetting at the end.
        seq_model = self.opt_model.seq_model
        tfrms = seq_model.gbl_tfrms
        tfrtm0 = tfrms[0]

        start_bundle = [r.ray[0] for r in self.rayset.values()]
        if abs(tfrtm0[1][2]) > self.start_offset:
            rot, t = setup_shift_of_ray_bundle(seq_model, self.start_offset)
            tfrms[0] = (rot, t)
            shift_start_of_ray_bundle(start_bundle, self.rayset.values(),
                                      rot, t)

        try:
            poly, bbox = self.render_shape(self.rayset,
                                           start_bundle, tfrms)
            cr = self.render_ray(self.rayset['00'].ray,
                                 start_bundle[0], tfrms)
            upr = self.render_ray(self.rayset['+Y'].ray,
                                  start_bundle[3], tfrms)
            lwr = self.render_ray(self.rayset['-Y'].ray,
                                  start_bundle[4], tfrms)
        finally:
            tfrms[0] = tfrtm0

        p = view.create_polygon(poly, rndr_clr)
        self.handles['shape'] = (p, bbox)

        cr_poly = view.create_polyline(cr)
        self.handles['00'] = (cr_poly, bbox_from_poly(cr))

        upr_poly = view.create_polyline(upr)
        self.handles['+Y'] = (upr_poly, bbox_from_poly(upr))

        lwr_poly = view.create_polyline(lwr)
        self.handles['-Y'] = (lwr_poly, bbox_from_poly(lwr))

        return self.handles

    def edit_ray_bundle_actions(self):
        actions = {}

        def on_select_ray(fig, handle, event):
            if handle is not 'shape':
                ray_table = self.ray_table_callback()
                ray_table.root = self.rayset[handle].ray
                fig.refresh_gui()

        actions['press'] = on_select_ray

        return actions


class LensLayout():
    def __init__(self, opt_model, **kwargs):
        self.opt_model = opt_model
        self.ray_table = None

        ele_model = self.opt_model.ele_model
        if len(ele_model.elements) == 0:
            ele_model.elements_from_sequence(self.opt_model.seq_model)

    def system_length(self, ele_bbox):
        osp = self.opt_model.optical_spec
        img_dist = abs(osp.parax_data[2].img_dist)
        ele_length = ele_bbox[1][0] - ele_bbox[0][0]
        return ele_length+img_dist

    def create_element_model(self, view):
        ele_model = self.opt_model.ele_model
        elements = [create_optical_element(self.opt_model, e)
                    for e in ele_model.elements]
        return elements

    def create_ray_model(self, view, start_offset):
        ray_bundles = []
        fov = self.opt_model.optical_spec.field_of_view
        wvl = self.opt_model.seq_model.central_wavelength()
        for i, fld in enumerate(fov.fields):
            fld_label = fov.index_labels[i]
            rb = RayBundle(self.opt_model, fld, fld_label, wvl, start_offset,
                           ray_table_callback=self.get_ray_table)
            ray_bundles.append(rb)
        return ray_bundles

    def get_ray_table(self):
        if self.ray_table is None:
            self.ray_table = appcmds.create_ray_table_model(self.opt_model,
                                                            None)
            gui_parent = self.opt_model.app_manager.gui_parent
            gui_parent.create_table_view(self.ray_table, "Ray Table")

        return self.ray_table