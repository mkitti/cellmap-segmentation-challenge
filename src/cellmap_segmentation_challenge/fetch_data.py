from typing import Generator, Sequence
from cellmap_schemas.annotation import CropGroup
import numpy as np
from xarray_ome_ngff import read_multiscale_array, read_multiscale_group

import zarr
import zarr.indexing
import zarr.storage
import os
from yarl import URL
from .utils.crops import CHALLENGE_CROPS, Crop
from zarr._storage.store import Store
from typing import Iterable
from concurrent.futures import ThreadPoolExecutor, wait
import toolz

def copy_store(*, keys: Iterable[str], source_store: Store, dest_store: Store):
    """
    Iterate over the keys, copying them from the source store to the dest store
    """
    for key in keys:
        dest_store[key] = source_store[key]

def partition_copy_store(*, keys, source_store, dest_store, batch_size, pool: ThreadPoolExecutor):
    keys_partitioned = toolz.partition_all(batch_size, keys)
    futures = [pool.submit(copy_store, keys=batch, source_store=source_store, dest_store=dest_store) for batch in keys_partitioned]
    wait(futures)

def _resolve_gt(root: URL, crop: Crop) -> URL:
    """
    Get the location of a ground truth crop relative to a root
    """
    return root.with_path(f'{crop.dataset}/{crop.dataset}.zarr/{crop.alignment}/labels/groundtruth/crop{crop.id}')

def _resolve_em(root: URL, crop: Crop) -> tuple[URL, URL, URL]:
    """
    Get the location(s) of the EM data for a crop, relative to a root. This is a tuple of URLs, because 
    not all datasets have em data with a consistent dtype.
    """
    dtypes = ('uint8', 'uint16', 'int16')
    return tuple(root.with_path(f"{crop.dataset}/{crop.dataset}.zarr/{crop.alignment}/em/fibsem-{dtype}") for dtype in dtypes)

def get_url(node: zarr.Group | zarr.Array) -> URL:
    store = node.store
    if hasattr(store, "path"):
        if hasattr(store, "fs"):
            protocol = (
                store.fs.protocol[0]
                if isinstance(store.fs.protocol, Sequence)
                else store.fs.protocol
            )
        else:
            protocol = "file"

        # fsstore keeps the protocol in the path, but not s3store
        store_path = store.path.split("://")[-1] if "://" in store.path else store.path
        return URL.build(scheme=protocol, host=store_path, path=node.path)

    msg = (
        f"The store associated with this object has type {type(store)}, which "
        "cannot be resolved to a url"
    )
    raise ValueError(msg)

def get_fibsem_path(crop_path: str) -> str:
    """
    Get the path to the reconstructed FIB-SEM data used to create the crop.
    Returns a uri that resolves to a zarr group
    """
    return ''

def get_chunk_keys(
    array: zarr.Array, region: tuple[slice, ...] = ()
) -> Generator[str, None, None]:
    """
    Get the keys for all the chunks in a Zarr array as a generator of strings.
    Returns keys relative to the path of the array.

    copied with modifications from https://github.com/janelia-cellmap/fibsem-tools/blob/2ff3326b38e5565d4860fdd50faaf1448afbb6ae/src/fibsem_tools/io/zarr/core.py#L191

    Parameters
    ----------
    array: zarr.core.Array
        The zarr array to get the chunk keys from
    region: tuple[slice, ...]
        The region in the zarr array get chunks keys from. Defaults to `()`, which
        will result in all the chunk keys being returned.
    Returns
    -------
    Generator[str, None, None]

    """
    indexer = zarr.indexing.BasicIndexer(region, array)
    chunk_coords = (idx.chunk_coords for idx in indexer)
    for cc in chunk_coords:
        yield array._chunk_key(cc).rsplit(array.path)[-1].lstrip('/')

def get_array_objects(node: zarr.Array, region: tuple[slice, ...] = ()) -> tuple[str, ...]:
    """
    Get a list of the objects supporting this array. 
    These objects may or may not exist in storage.
    """
    
    array_metadata_key = '.zarray'
    attrs_key = '.zattrs'
    ckeys = get_chunk_keys(node, region=region)

    out = tuple([array_metadata_key, attrs_key, *ckeys])
    return out

def get_group_objects(node: zarr.Group) -> tuple[str, ...]:
    group_metadata_key = '.zgroup'
    attrs_key = '.zattrs'
    results: tuple[str] = (group_metadata_key, attrs_key)

    for name, subnode in node.items():
        if isinstance(subnode, zarr.Array):
            subobjects = get_array_objects(subnode)
        else:
            subobjects = get_group_objects(subnode)
        results += tuple(map(lambda v: '/'.join([name, v]), subobjects))
    return results

def read_group(path: str, **kwargs) -> zarr.Group:
    return zarr.open_group(path, mode='r')

def subset_to_slice(outer_array, inner_array) -> tuple[slice, ...]:
        subregion = outer_array.sel(inner_array.coords, 'nearest')
        out = ()
        for dim, value in outer_array.coords():
            start = np.where(value == subregion.coords[dim][0])[0].take(0)
            stop = np.where(value == subregion.coords[dim][-1])[0].take(0)
            step = 1
            out += slice(start, stop, step)
        return out

def prepare_fetch_crop(crop_path: str, fibsem_padding_vox: int | tuple[int, ...] = 0) -> tuple[tuple[str, str], ...]:

    if isinstance(fibsem_padding_vox, int):
        fibsem_padding_vox = (fibsem_padding_vox,) * 3

    crop_zgroup = zarr.open_group(crop_path, mode='r')
    fibsem_path = get_fibsem_path(crop_path)

    fibsem_zgroup = zarr.open_group(fibsem_path)

    # generate a tuple of crop objects to copy
    crop_objects_to_copy = get_group_objects(crop_zgroup)
    crop_xarray = read_multiscale_array(
        crop_zgroup['s0'], 
        array_wrapper={'name': 'dask_array', 'config': {'chunks': "auto"}})
    
    fibsem_xarrays = read_multiscale_group(fibsem_zgroup)
    fibsem_objects_to_copy = ('.zgroup', '.zattrs')
    for name, value in fibsem_xarrays.items():

    # crop each datarray in object space


    # generate a tuple of fibsem objects to copy, based on the location of the crop
        pass
