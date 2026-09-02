# WMS Multiple Field Settings Plan

Related Progress: [WMS Multiple Field Settings Progress](../progress/wms-multiple-field-settings.md)

Make WMS use the same `file_metadata.availableLayers` structure as ESRI MapServer.
TileServer discovers named WMS layers through GetCapabilities, and field requests use
the selected WMS layer name when calling WFS DescribeFeatureType.
