"""
Model exported as python.
Name : PTHA
With QGIS : 34014
"""

from qgis.core import QgsProcessing
from qgis.core import QgsProcessingAlgorithm
from qgis.core import QgsProcessingMultiStepFeedback
from qgis.core import QgsProcessingParameterRasterLayer
from qgis.core import QgsProcessingParameterVectorLayer, QgsProcessingParameterFeatureSource, QgsProcessingParameterExtent
from qgis.core import QgsProcessingParameterFeatureSink, QgsProcessingUtils, QgsProcessingContext
from qgis.core import QgsProcessingParameterEnum
from qgis.core import QgsVectorLayer, QgsExpression, QgsProcessingException
from qgis.core import QgsFillSymbol
import processing
from qgis.PyQt.QtGui import QIcon
import os

 
class Ptha(QgsProcessingAlgorithm):

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer('dem', 'DEM', defaultValue=None))
        #self.addParameter(QgsProcessingParameterVectorLayer('ptha_points', 'PTHA Points', defaultValue=None))
        #self.addParameter(QgsProcessingParameterVectorLayer('villagetown_boundary', 'Village/Town Boundary', defaultValue=None))
        self.addParameter(QgsProcessingParameterExtent('boundary','Area of Interest'))
        self.addParameter(
            QgsProcessingParameterEnum(
                'year',
                'Return Period',
                options=['10','25','50','100','250','500','1000','2500','5000','10000'],
                defaultValue=3
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                'uncertainty',
                'Stage Estimate Type',
                options=['median','mean','upper_ci','lower_ci','16pc','84pc'],
                defaultValue=0
            )
        )
        self.addParameter(QgsProcessingParameterFeatureSink('HazardZone', 'Hazard Zone', type=QgsProcessing.TypeVectorAnyGeometry, createByDefault=True, defaultValue='TEMPORARY_OUTPUT'))
        


    def processAlgorithm(self, parameters, context, model_feedback):
        plugin_dir = os.path.dirname(__file__)
        csv_path = os.path.join(plugin_dir, "revised1_tsunami_stages_at_fixed_return_periods.csv")
        uri = f"file:///{csv_path}?delimiter=,&xField=lon&yField=lat&crs=EPSG:4326"
        ptha_points = QgsVectorLayer(uri, "PTHA Points", "delimitedtext")
        #ptha_points = QgsVectorLayer(csv_path, "PTHA Points", "ogr")
        # Use a multi-step feedback, so that individual child algorithm progress reports are adjusted for the
        # overall progress through the model
        feedback = QgsProcessingMultiStepFeedback(6, model_feedback)
        results = {}
        outputs = {}

        year_options = ['10','25','50','100','250','500','1000','2500','5000','10000']
        year = year_options[parameters['year']]
        uncertainty_options = ['median','mean','upper_ci','lower_ci','16pc','84pc']
        uncertainty = uncertainty_options[parameters['uncertainty']]
        
        dem_layer = self.parameterAsRasterLayer(parameters, 'dem', context)
        extent = self.parameterAsExtent(parameters, 'boundary', context)

        
        extent_polygon = processing.run(
            'native:extenttolayer',
            {
                'INPUT': extent,
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
            },
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )['OUTPUT']

        # Clip raster by mask layer
        alg_params = {
            'ALPHA_BAND': False,
            'CROP_TO_CUTLINE': True,
            'DATA_TYPE': 0,  # Use Input Layer Data Type
            'EXTRA': '',
            'INPUT': dem_layer,
            'KEEP_RESOLUTION': False,
            'MASK': extent_polygon,
            'MULTITHREADING': False,
            'NODATA': None,
            'OPTIONS': None,
            'SET_RESOLUTION': False,
            'SOURCE_CRS': None,
            'TARGET_CRS': None,
            'TARGET_EXTENT': None,
            'X_RESOLUTION': None,
            'Y_RESOLUTION': None,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['ClipRasterByMaskLayer'] = processing.run('gdal:cliprasterbymasklayer', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(1)
        if feedback.isCanceled():
            return {}



        # Join attributes by nearest
        alg_params = {
            'DISCARD_NONMATCHING': False,
            'FIELDS_TO_COPY': [''],
            'INPUT': extent_polygon,
            'INPUT_2': ptha_points,
            'MAX_DISTANCE': None,
            'NEIGHBORS': 1,
            'PREFIX': None,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['JoinAttributesByNearest'] = processing.run('native:joinbynearest', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
        

        feedback.setCurrentStep(2)
        if feedback.isCanceled():
            return {}
        
        if uncertainty == 'mean':
            stage_field = f"STAGE_{year}"
        else:
            stage_field = f"STAGE_{uncertainty}_{year}"
        # year = parameters['year']
        # uncertainty = parameters['uncertainty']
        
        # Retain fields
        alg_params = {
            'FIELDS': [stage_field, 'elev'],
            'INPUT': outputs['JoinAttributesByNearest']['OUTPUT'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['RetainFields'] = processing.run('native:retainfields', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(3)
        if feedback.isCanceled():
            return {}

        # Rename field
        alg_params = {
            'FIELD': stage_field,
            'INPUT': outputs['RetainFields']['OUTPUT'],
            'NEW_NAME': 'Main',
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['RenameField'] = processing.run('native:renametablefield', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(4)
        if feedback.isCanceled():
            return {}

        # Field calculator
        alg_params = {
            'FIELD_LENGTH': 3,
            'FIELD_NAME': 'PTHA_WL',
            'FIELD_PRECISION': 3,
            'FIELD_TYPE': 0,  # Decimal (double)
            'FORMULA': 'sqrt(sqrt(abs("elev"))) * "Main"',
            'INPUT': outputs['RenameField']['OUTPUT'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        try:
            outputs['FieldCalculator'] = processing.run('native:fieldcalculator', alg_params, context=context, feedback=feedback, is_child_algorithm=True)
        except Exception:
            raise QgsProcessingException(
                "The selected PTHA point does not contain a valid tsunami stage value "
                "for the chosen return period and uncertainty level.\n\n"
                "This occurs because some values in the PTHA dataset are stored as "
                "missing data (NA) when wave heights are extremely small or large.\n\n"
                "Please select a different return period or uncertainty option."
            )
        feedback.setCurrentStep(5)
        if feedback.isCanceled():
            return {}
        # Get PTHA water level value
        layer = QgsProcessingUtils.mapLayerFromString(outputs['FieldCalculator']['OUTPUT'], context)
        
        ptha_wl = None
        for f in layer.getFeatures():
            ptha_wl = f['PTHA_WL']
            break
        
        # Raster Calculator (DEM < PTHA_WL)
        alg_params = {
            'EXPRESSION': f'("{outputs["ClipRasterByMaskLayer"]["OUTPUT"]}@1" < {ptha_wl}) AND ("{outputs["ClipRasterByMaskLayer"]["OUTPUT"]}@1" > 0)',
            'LAYERS': [outputs['ClipRasterByMaskLayer']['OUTPUT']],
            'CELLSIZE': 0,
            'EXTENT': None,
            'CRS': None,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        
        outputs['RasterCalculator'] = processing.run(
            'qgis:rastercalculator',
            alg_params,
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )
        
        # Raster to polygon
        alg_params = {
            'FIELD_NAME': 'VALUE',
            'INPUT_RASTER': outputs['RasterCalculator']['OUTPUT'],
            'RASTER_BAND': 1,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        
        outputs['FloodPixels'] = processing.run(
            'native:pixelstopolygons',
            alg_params,
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )
        
        alg_params = {
            'EXPRESSION': '"VALUE" = 1',
            'INPUT': outputs['FloodPixels']['OUTPUT'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        
        outputs['FloodArea'] = processing.run(
            'native:extractbyexpression',
            alg_params,
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )
        
        # WL
        alg_params = {
            'FIELDS': QgsExpression("'PTHA_WL'").evaluate(),
            'INPUT': outputs['FieldCalculator']['OUTPUT'],
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        outputs['Wl'] = processing.run('native:retainfields', alg_params, context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(6)
        if feedback.isCanceled():
            return {}

         
        # Buffer flood polygons
        alg_params = {
            'INPUT': outputs['FloodArea']['OUTPUT'],
            'DISTANCE': 0.00001,
            'SEGMENTS': 5,
            'END_CAP_STYLE': 0,
            'JOIN_STYLE': 0,
            'MITER_LIMIT': 2,
            'DISSOLVE': False,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }
        
        outputs['BufferFlood'] = processing.run(
            'native:buffer',
            alg_params,
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )
        
        # Dissolve
        alg_params = {
            'FIELD': [],
            'INPUT': outputs['BufferFlood']['OUTPUT'],
            'SEPARATE_DISJOINT': False,
            'OUTPUT': parameters['HazardZone']
        }
        
        outputs['Dissolve'] = processing.run(
            'native:dissolve',
            alg_params,
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )
        
        haz_layer = outputs['Dissolve']['OUTPUT']
        layer = QgsProcessingUtils.mapLayerFromString(haz_layer, context)

        symbol = QgsFillSymbol.createSimple({
            'color': '255,165,0,178',   # orange with ~70% opacity
            'outline_style': 'no'
        })

        layer.renderer().setSymbol(symbol)
        layer.triggerRepaint()

        context.addLayerToLoadOnCompletion(
            haz_layer,
            QgsProcessingContext.LayerDetails(
                f"PTHA_{year}yr_Hazard_Zone",
                context.project(),
                "OUTPUT"
            )
        )
        
        results['HazardZone'] = haz_layer
        return results

    def name(self):
        return 'PTHA'

    def displayName(self):
        return 'PTHA Based Tsunami Inundation'

    def group(self):
        return ''

    def groupId(self):
        return ''

    def createInstance(self):
        return Ptha()
    def icon(self):
        plugin_dir = os.path.dirname(__file__)
        icon_path = os.path.join(plugin_dir, "icon.png")
        return QIcon(icon_path)
