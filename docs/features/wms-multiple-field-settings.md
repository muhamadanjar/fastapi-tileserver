# WMS Multiple Field Settings

Related Plan: [WMS Multiple Field Settings Plan](../plans/wms-multiple-field-settings.md)  
Related Progress: [WMS Multiple Field Settings Progress](../progress/wms-multiple-field-settings.md)

ESRI MapServer and WMS now use the same `file_metadata.availableLayers` structure:
each entry has a stable `id` and a display `name`. ESRI IDs are numeric service layer
IDs; WMS IDs are named WMS layers discovered from GetCapabilities.

The frontend persists field configuration beneath `file_metadata.fields[availableLayer.id]`.
For field discovery, ESRI sends `layerIndex`; WMS sends `layerName`, which TileServer
uses as the WFS `DescribeFeatureType` type name.
