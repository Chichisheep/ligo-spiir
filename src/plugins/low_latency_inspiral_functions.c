#include "low_latency_inspiral_functions.h"
#include <stdio.h>
#include <gsl/gsl_math.h>
#include <gsl/gsl_vector.h>
#include <gsl/gsl_matrix.h>
#include <math.h>
#include <gsl/gsl_linalg.h>

/* FIXME: this is a place holder and needs to be implemented rigorously with  
 * lal functions */
int generate_bank_svd(gsl_matrix **U, gsl_vector **S, gsl_matrix **V,
                           gsl_vector **chifacs,
                           double chirp_mass_start, int base_sample_rate,
                           int down_samp_fac, int numtemps, double t_start,
                           double t_end, double tmax, double tolerance,
			   int verbose)
  {
  FILE *FP = NULL;
  double c8_3 = 8.0/3.0;
  double c3_8 = 3.0/8.0;
  double c5_256 = 5.0/256.0;
  double c = 299792458;
  double G = 6.67428e-11;
  double Msol = 1.98893e30;
  double M = chirp_mass_start;
  double Mg = M*Msol*G/c/c/c;
  double ny_freq = 0.5*base_sample_rate;
  double T = 0;
  int i = 0;
  int j = 0;
  int svd_err_code = 0;
  int numsamps = floor((double) (t_end-t_start) * base_sample_rate 
               / down_samp_fac);
  double dt = (double) down_samp_fac/base_sample_rate;
  double tmpltpower = 0;
  double h=0;
  double norm = 0;
  double maxFreq = 0;
  gsl_vector *work_space = gsl_vector_calloc(numtemps);
  gsl_matrix *work_space_matrix = gsl_matrix_calloc(numtemps,numtemps);
  if (verbose) FP = fopen("tmpbankdata.dat","w");
  *U = gsl_matrix_calloc(numsamps,numtemps);
  *S = gsl_vector_calloc(numtemps);
  *V = gsl_matrix_calloc(numtemps,numtemps);
  gsl_matrix *UT=NULL;
  /*gsl_matrix *VT=NULL;*/
  gsl_matrix *Utmp = NULL;
  /*gsl_matrix *Vtmp = NULL;*/
  *chifacs = gsl_vector_calloc(numtemps);

  if (verbose) printf("allocated matrices...\n");
  /* create the templates in the bank */
  for (i=0;i<numtemps;i++)
    {
    if (verbose) printf("template number %d...\n",i);
    /* increment the mass */
    /* this coefficient should maybe be 0.0001 */
    M = chirp_mass_start + 0.0003*i*M/0.7;
    Mg = M*Msol*G/c/c/c;
    T = -1.0/( pow(M_PI * Mg * ny_freq, 8.0/3.0) / (5.0/256.0*Mg) )
      - t_start;
    /* FIXME We should check that the frequency at this time fits within the */
    /* downsampled rate!!! 						     */
    maxFreq = (1.0/(M_PI*Mg)) * (pow((5.0/256.0)*(Mg/(-T)),3.0/8.0));
    if (verbose) printf("T %e nyfreq %e chirpm %e max freq %e\n",T,ny_freq,M,maxFreq);

    if (maxFreq > ((double) (ny_freq/down_samp_fac+1.0/base_sample_rate)) )
      {
      fprintf(stderr,
              "cannot generate template segment at requested sample rate\n");
      return 1;
      }
    h = 0;
    norm = normalize_template(Mg, T, tmax, base_sample_rate);
    for(j =numsamps-1; j>=0; j--)
      {
      h = 4.0*Mg*pow(5.0/256.0*(Mg/(-T+dt*j)),0.25)
        * sin(-2.0/2.0/M_PI* pow((-T+dt*j)/(5.0*Mg),(5.0/8.0)));
      tmpltpower+=h*h;		 
      gsl_matrix_set(*U,numsamps-1-j,i,h/norm);
      if (verbose && i ==0) fprintf(FP,"%e\n",h/norm);
      }
    gsl_vector_set(*chifacs,i,sqrt(tmpltpower));
    }
  /*gsl_matrix_fprintf(FP,*U,"%f");*/
  if (FP) fclose(FP);
  svd_err_code = gsl_linalg_SV_decomp_mod(*U, work_space_matrix, 
                                             *V, *S, work_space);
  /*svd_err_code = gsl_linalg_SV_decomp(*U,*V, *S, work_space);*/
  /*svd_err_code = gsl_linalg_SV_decomp_jacobi(*U, *V, *S);*/
  if ( svd_err_code ) 
    {
    fprintf(stderr,"could not do SVD \n");
    return 1; 
    }
  trim_matrix(U,V,S,tolerance);
  if (verbose) fprintf(stderr,"sub template number = %d\n",(*U)->size2);
  for (i = 0; i < (*S)->size; i++)
    {
    for (j = 0; j < (*V)->size1; j++)
      {
      gsl_matrix_set(*V,j,i,gsl_vector_get(*S,i)*gsl_matrix_get(*V,j,i));
      }
    }
  printf("U %d,%d V %d,%d\n\n",(*U)->size1,(*U)->size2,(*V)->size1,(*V)->size2);
  not_gsl_matrix_transpose(U,&UT);
  /*not_gsl_matrix_transpose(V,&VT);*/
  Utmp = *U;
  /*Vtmp = *V;*/
  *U = UT;
  /**V = VT;*/
  gsl_matrix_free(Utmp);
  /*gsl_matrix_free(Vtmp);*/
  gsl_vector_free(work_space);
  gsl_matrix_free(work_space_matrix);
  return 0;
  }

/* FIXME: this is a terrible idea! */
int not_gsl_matrix_transpose(gsl_matrix **in, gsl_matrix **out)
  {
  int i = 0;
  int j = 0;
  printf("size1 %d, size2 %d\n\n",(*in)->size1,(*in)->size2);
  *out = gsl_matrix_calloc((*in)->size2,(*in)->size1);
  
  for (i=0; i< (*in)->size1; i++)
    {
    for (j=0; j< (*in)->size2; j++)
      {
      gsl_matrix_set(*out,j,i,gsl_matrix_get(*in,i,j));
      }
    }
  }

double normalize_template(double M, double ts, double duration,
                                int fsamp)

  {
  int numsamps = fsamp*duration;
  double tmpltpower = 0;
  double h = 0;
  int i = 0;
  double dt = 1.0/fsamp;
  for (i=0; i< numsamps; i++)
    {
    h = 4.0 * M * pow(5.0/256.0*(M/(-ts+dt*i)),0.25) 
      * sin(-2.0/2.0/M_PI * pow((-ts+dt*i)/(5.0*M),(5.0/8.0)));
    tmpltpower+=h*h;
    }
  return sqrt(tmpltpower);
   
  }

 int trim_matrix(gsl_matrix **U, gsl_matrix **V, gsl_vector **S, 
                        double tolerance)
  {
  double sumb = 0;
  double cumsumb = 0;
  int maxb = 0;
  int i = 0;
  /*for (i = 0; i < (*S)->size; i++) 
    {
    sumb+= gsl_vector_get(*S,i);
    printf("S(%d) = %f",i,gsl_vector_get(*S,i));
    }*/
  sumb = gsl_vector_get(*S,0);
  for (i = 0; i < (*S)->size; i++)
    {
    cumsumb = 1-gsl_vector_get(*S,i)/sumb;
    if ((cumsumb*cumsumb) > tolerance) break;
    }
  maxb = i;/* (*S)->size;*/
  if (not_gsl_matrix_chop(U,(*U)->size1,maxb)) return 1;
  if (not_gsl_matrix_chop(V,(*V)->size1,maxb)) return 1;
  if (not_gsl_vector_chop(S,maxb)) return 1;
  return;
  }

/*FIXME this is terrible and needs to be made more efficient!!!!!!!*/
 int not_gsl_matrix_chop(gsl_matrix **M, size_t m, size_t n)
  {
  /*FILE *FP = NULL;*/
  gsl_matrix *tmp = (*M);
  gsl_matrix *newM = NULL;
  int i = 0; 
  int j = 0;
  
  if ( (*M)->size1 < m ) return 1;
  if ( (*M)->size2 < n ) return 1;
  /*FP = fopen("svd.dat","w");*/
  newM = gsl_matrix_calloc(m,n);

  for (i=0; i<m; i++)
    {
    for (j=0; j<n; j++)
      {
      gsl_matrix_set(newM,i,j,gsl_matrix_get(*M,i,j));
      /*fprintf(FP,"%e\n",gsl_matrix_get(*M,i,j));*/
      }
    }
  *M = newM;
  gsl_matrix_free(tmp);
  return 0;
  }

/*FIXME this is terrible and needs to be made more efficient!!!!!!!*/
 int not_gsl_vector_chop(gsl_vector **V, size_t m)
  {

  gsl_vector *tmp = (*V);
  gsl_vector *newV = NULL;
  int i = 0;

  if ( (*V)->size < m ) return 1;
  newV = gsl_vector_calloc(m);
  for (i=0; i<m; i++)
    {
    gsl_vector_set(newV,i,gsl_vector_get(*V,i));
    }
  *V = newV;
  gsl_vector_free(tmp);
  return 0;
  }
